import { invoke } from "@tauri-apps/api/core";
import { SegmentMuxer } from "./muxer";
import { SegmentClock } from "./segments";

/** H.264 Main profile, level 3.1: enough for 1280x720 at 30 fps. */
const H264_MAIN_31 = "avc1.4d401f";
/** Frames allowed to wait in the encoder before new ones are dropped. */
const MAX_ENCODE_QUEUE = 30;

export interface RecorderOptions {
  segmentSeconds: number;
  frameRate: number;
  videoBitrate: number;
  audioBitrate: number;
}

export interface SavedSegment {
  index: number;
  bytes: number;
  videoFrames: number;
  audioChunks: number;
  audioDropped: number;
  finishMs: number;
  ipcMs: number;
  rustMicros: number;
}

export interface RecorderReport {
  videoConfig: VideoEncoderConfig;
  hardwareEncoderSupported: boolean;
  audioConfig: AudioEncoderConfig | null;
  framesEncoded: number;
  framesDropped: number;
  maxEncodeQueue: number;
  /** First capture timestamps (µs), to check the tracks share one clock. */
  firstVideoUs: number | null;
  firstAudioUs: number | null;
  segments: SavedSegment[];
  errors: string[];
}

/**
 * The raw frames of a media track. Chromium's `MediaStreamTrackProcessor` yields `VideoFrame`s
 * for video tracks and `AudioData` for audio tracks; TypeScript's DOM typings only describe
 * specific video-track overloads, so the constructor is typed here once.
 */
function trackFrames<T extends VideoFrame | AudioData>(track: MediaStreamTrack): ReadableStream<T> {
  const Processor = MediaStreamTrackProcessor as unknown as new (init: {
    track: MediaStreamTrack;
  }) => { readable: ReadableStream<T> };
  return new Processor({ track }).readable;
}

interface SaveResult {
  bytes: number;
  micros: number;
}

/**
 * Records a camera (and optional microphone) stream into self-contained MP4 segments with
 * WebCodecs and Mediabunny, handing each finished segment to Rust over raw IPC.
 */
export class CameraRecorder {
  private readonly clock: SegmentClock;
  private readonly muxers = new Map<number, SegmentMuxer>();
  private readonly readers: ReadableStreamDefaultReader<VideoFrame | AudioData>[] = [];
  private readonly pumps: Promise<void>[] = [];
  private videoDecoderConfig: VideoDecoderConfig | undefined;
  private audioDecoderConfig: AudioDecoderConfig | undefined;
  private lastVideoSegment = -1;
  // Chromium stamps camera frames with the system capture clock but microphone data with
  // time since the stream started. Each offset maps a track's clock onto performance.now().
  private videoClockUs: number | null = null;
  private audioClockUs: number | null = null;
  private running = true;
  private queue: Promise<void> = Promise.resolve();
  private readonly videoEncoder: VideoEncoder;
  private readonly audioEncoder: AudioEncoder | null;

  private constructor(
    private readonly options: RecorderOptions,
    readonly report: RecorderReport,
    hasAudio: boolean,
  ) {
    this.clock = new SegmentClock(options.segmentSeconds * 1_000_000);
    this.videoEncoder = new VideoEncoder({
      output: (chunk, metadata) =>
        this.enqueue(() => this.handleVideo(chunk, metadata?.decoderConfig)),
      error: (error) => this.report.errors.push(`video encoder: ${error.message}`),
    });
    this.audioEncoder = hasAudio
      ? new AudioEncoder({
          output: (chunk, metadata) =>
            this.enqueue(() => this.handleAudio(chunk, metadata?.decoderConfig)),
          error: (error) => this.report.errors.push(`audio encoder: ${error.message}`),
        })
      : null;
  }

  static async start(stream: MediaStream, options: RecorderOptions): Promise<CameraRecorder> {
    const video = stream.getVideoTracks()[0];
    if (!video) {
      throw new Error("The stream has no video track.");
    }
    const audio = stream.getAudioTracks()[0];
    const settings = video.getSettings();
    const preferred: VideoEncoderConfig = {
      codec: H264_MAIN_31,
      width: settings.width ?? 1280,
      height: settings.height ?? 720,
      bitrate: options.videoBitrate,
      framerate: options.frameRate,
      hardwareAcceleration: "prefer-hardware",
      latencyMode: "realtime",
      avc: { format: "avc" },
    };
    const hardware = await VideoEncoder.isConfigSupported(preferred);
    const videoConfig: VideoEncoderConfig = hardware.supported
      ? preferred
      : { ...preferred, hardwareAcceleration: "no-preference" };

    let audioConfig: AudioEncoderConfig | null = null;
    if (audio) {
      const audioSettings = audio.getSettings();
      audioConfig = {
        codec: "opus",
        sampleRate: audioSettings.sampleRate ?? 48_000,
        numberOfChannels: audioSettings.channelCount ?? 1,
        bitrate: options.audioBitrate,
      };
    }

    const report: RecorderReport = {
      videoConfig,
      hardwareEncoderSupported: hardware.supported === true,
      audioConfig,
      framesEncoded: 0,
      framesDropped: 0,
      maxEncodeQueue: 0,
      firstVideoUs: null,
      firstAudioUs: null,
      segments: [],
      errors: [],
    };
    const recorder = new CameraRecorder(options, report, audioConfig !== null);
    recorder.videoEncoder.configure(videoConfig);
    if (recorder.audioEncoder && audioConfig && audio) {
      recorder.audioEncoder.configure(audioConfig);
      recorder.pumps.push(recorder.pumpAudio(audio));
    }
    recorder.pumps.push(recorder.pumpVideo(video));
    return recorder;
  }

  /** Stops capture, flushes the encoders and saves the last segments. */
  async stop(): Promise<RecorderReport> {
    this.running = false;
    await Promise.all(this.readers.map((reader) => reader.cancel()));
    await Promise.all(this.pumps);
    await this.videoEncoder.flush();
    await this.audioEncoder?.flush();
    await this.queue;
    await this.finishBefore(Number.POSITIVE_INFINITY);
    this.videoEncoder.close();
    this.audioEncoder?.close();
    return this.report;
  }

  private async pumpVideo(track: MediaStreamTrack): Promise<void> {
    const reader = trackFrames<VideoFrame>(track).getReader();
    this.readers.push(reader);
    while (this.running) {
      const { value: frame, done } = await reader.read();
      if (done || !frame) {
        return;
      }
      this.report.firstVideoUs ??= frame.timestamp;
      this.videoClockUs ??= frame.timestamp - performance.now() * 1_000;
      const { segment } = this.clock.place(frame.timestamp);
      const queued = this.videoEncoder.encodeQueueSize;
      this.report.maxEncodeQueue = Math.max(this.report.maxEncodeQueue, queued);
      if (queued > MAX_ENCODE_QUEUE && segment === this.lastVideoSegment) {
        this.report.framesDropped += 1;
      } else {
        // The first frame of every segment is a keyframe, so each file plays on its own.
        this.videoEncoder.encode(frame, { keyFrame: segment !== this.lastVideoSegment });
        this.lastVideoSegment = segment;
        this.report.framesEncoded += 1;
      }
      frame.close();
    }
  }

  private async pumpAudio(track: MediaStreamTrack): Promise<void> {
    const reader = trackFrames<AudioData>(track).getReader();
    this.readers.push(reader);
    while (this.running) {
      const { value: data, done } = await reader.read();
      if (done || !data) {
        return;
      }
      this.report.firstAudioUs ??= data.timestamp;
      this.audioClockUs ??= data.timestamp - performance.now() * 1_000;
      this.audioEncoder?.encode(data);
      data.close();
    }
  }

  private enqueue(work: () => Promise<void>): void {
    this.queue = this.queue.then(work).catch((error: unknown) => {
      this.report.errors.push(error instanceof Error ? error.message : String(error));
    });
  }

  private async handleVideo(chunk: EncodedVideoChunk, config?: VideoDecoderConfig) {
    if (config) {
      this.videoDecoderConfig = config;
    }
    const { segment } = this.clock.place(chunk.timestamp);
    let muxer = this.muxers.get(segment);
    if (!muxer) {
      if (chunk.type !== "key") {
        this.report.errors.push(`segment ${segment} would start with a delta frame`);
        return;
      }
      muxer = new SegmentMuxer(segment, chunk.timestamp, this.options.frameRate);
      await muxer.start();
      this.muxers.set(segment, muxer);
      if (!this.audioEncoder) {
        await this.finishBefore(segment);
      }
    }
    await muxer.addVideo(chunk, this.videoDecoderConfig);
  }

  private async handleAudio(chunk: EncodedAudioChunk, config?: AudioDecoderConfig) {
    if (config) {
      this.audioDecoderConfig = config;
    }
    if (this.videoClockUs === null || this.audioClockUs === null) {
      return;
    }
    // The chunk's time on the video clock.
    const timestamp = chunk.timestamp - this.audioClockUs + this.videoClockUs;
    let target: SegmentMuxer | undefined;
    for (const muxer of this.muxers.values()) {
      if (muxer.baseUs <= timestamp && (!target || muxer.baseUs > target.baseUs)) {
        target = muxer;
      }
    }
    if (!target) {
      return;
    }
    // Audio has reached this segment, so every older segment is complete.
    await this.finishBefore(target.index);
    await target.addAudio(chunk, this.audioDecoderConfig, timestamp);
  }

  private async finishBefore(index: number): Promise<void> {
    const done = [...this.muxers.values()].filter((muxer) => muxer.index < index);
    for (const muxer of done) {
      this.muxers.delete(muxer.index);
      const finishing = performance.now();
      const bytes = await muxer.finish();
      const finishMs = performance.now() - finishing;
      const sending = performance.now();
      const saved = await invoke<SaveResult>("spike_save_segment", bytes, {
        headers: { "x-hv-kind": "camera", "x-hv-seq": String(muxer.index) },
      });
      this.report.segments.push({
        index: muxer.index,
        bytes: saved.bytes,
        videoFrames: muxer.videoFrames,
        audioChunks: muxer.audioChunks,
        audioDropped: muxer.audioDropped,
        finishMs,
        ipcMs: performance.now() - sending,
        rustMicros: saved.micros,
      });
    }
  }
}
