import { messageOf, type RecordingContext, type TrackRecorder, type TrackReport } from "./context";
import { chooseCameraFormat, type Format, MIC_OPUS, type WebviewTrack } from "./formats";
import { SegmentFile } from "./segment-file";
import { BoundaryIndex, type SegmentTiming, TrackTimeline } from "./timing";

/** H.264 Main profile, level 3.1: enough for 1280x720 at 30 fps. */
const H264_MAIN_31 = "avc1.4d401f";
/** Frames allowed to wait in the encoder before new ones are dropped. */
const MAX_ENCODE_QUEUE = 30;

/**
 * The raw frames of a media track. Chromium's `MediaStreamTrackProcessor` yields `VideoFrame`s
 * for video tracks and `AudioData` for audio tracks; the DOM typings only describe the video
 * overload, so the constructor is typed here once.
 */
function trackFrames<T extends VideoFrame | AudioData>(track: MediaStreamTrack): ReadableStream<T> {
  const Processor = MediaStreamTrackProcessor as unknown as new (init: {
    track: MediaStreamTrack;
  }) => { readable: ReadableStream<T> };
  return new Processor({ track }).readable;
}

/** Whether this webview can record with WebCodecs (otherwise MediaRecorder is used). */
export function webCodecsAvailable(): boolean {
  return (
    typeof VideoEncoder !== "undefined" &&
    typeof AudioEncoder !== "undefined" &&
    typeof MediaStreamTrackProcessor !== "undefined"
  );
}

/**
 * Turns one encoder's output into segment files: a new file at every segment boundary
 * (placed on the encoder's input by a {@link TrackTimeline}), each handed to the sink with its
 * server-time start once the next one begins.
 */
class SegmentWriter {
  private readonly boundaries = new BoundaryIndex();
  private readonly timings = new Map<number, SegmentTiming>();
  private current: SegmentFile | null = null;
  private decoderConfig: VideoDecoderConfig | AudioDecoderConfig | undefined;
  private queue: Promise<void> = Promise.resolve();
  readonly report: TrackReport;

  constructor(
    private readonly kind: "video" | "audio",
    track: WebviewTrack,
    readonly format: Format,
    private readonly ctx: RecordingContext,
    private readonly fallbackDurationS: number,
  ) {
    this.report = {
      track,
      mode: "webcodecs",
      format,
      segments: 0,
      bytes: 0,
      dropped: 0,
      errors: [],
    };
  }

  /** A segment started on the encoder's input at this timestamp. */
  started(timestampUs: number, seq: number): void {
    this.boundaries.add(timestampUs, seq);
  }

  /** The timeline closed a segment (its start and length are now known). */
  timed(timing: SegmentTiming | null): void {
    if (timing) {
      this.timings.set(timing.seq, timing);
    }
  }

  /** An encoder output, in order. */
  push(
    chunk: EncodedVideoChunk | EncodedAudioChunk,
    config: VideoDecoderConfig | AudioDecoderConfig | undefined,
  ): void {
    if (config) {
      this.decoderConfig = config;
    }
    this.enqueue(() => this.write(chunk));
  }

  /** Waits for every chunk so far, then delivers the open file. */
  async close(): Promise<TrackReport> {
    await this.queue;
    const last = this.current;
    this.current = null;
    if (last) {
      await this.deliver(last);
    }
    return this.report;
  }

  fail(message: string): void {
    this.report.errors.push(message);
    this.ctx.onError(this.report.track, message);
  }

  private enqueue(work: () => Promise<void>): void {
    this.queue = this.queue.then(work).catch((error: unknown) => this.fail(messageOf(error)));
  }

  private async write(chunk: EncodedVideoChunk | EncodedAudioChunk): Promise<void> {
    const seq = this.boundaries.seqAt(chunk.timestamp);
    if (!this.current || this.current.seq !== seq) {
      if (this.current) {
        const finished = this.current;
        this.current = null;
        await this.deliver(finished);
      }
      if (this.kind === "video" && chunk.type !== "key") {
        // Every file must start with a keyframe; wait for the encoder's next one.
        this.report.dropped += 1;
        return;
      }
      this.current = new SegmentFile(
        this.kind,
        this.format,
        seq,
        chunk.timestamp,
        this.fallbackDurationS,
      );
      await this.current.start();
      this.boundaries.forgetBefore(seq);
    }
    await this.current.add(chunk, this.decoderConfig);
  }

  private async deliver(file: SegmentFile): Promise<void> {
    this.report.dropped += file.dropped;
    if (file.packets === 0) {
      return;
    }
    const bytes = await file.finish();
    const timing = this.timings.get(file.seq);
    this.timings.delete(file.seq);
    if (!timing) {
      this.fail(`segment ${file.seq} has no timing`);
      return;
    }
    await this.ctx.sink(
      {
        track: this.report.track,
        seq: file.seq,
        startedAtMs: timing.startedAtMs,
        durationMs: timing.durationMs,
        container: this.format.container,
        codec: this.format.codec,
      },
      bytes,
    );
    this.report.segments += 1;
    this.report.bytes += bytes.byteLength;
  }
}

/** Reads a track's raw frames, places them on the timeline and feeds the encoder. */
abstract class WebCodecsTrack<T extends VideoFrame | AudioData> implements TrackRecorder {
  protected readonly timeline: TrackTimeline;
  private reader: ReadableStreamDefaultReader<T> | null = null;
  private pump: Promise<void> = Promise.resolve();
  private running = true;

  protected constructor(
    readonly track: WebviewTrack,
    protected readonly writer: SegmentWriter,
    ctx: RecordingContext,
  ) {
    this.timeline = new TrackTimeline(ctx.time, ctx.planner);
  }

  protected begin(media: MediaStreamTrack): void {
    this.reader = trackFrames<T>(media).getReader();
    this.pump = this.read(this.reader).catch((error: unknown) =>
      this.writer.fail(messageOf(error)),
    );
  }

  async stop(): Promise<TrackReport> {
    this.running = false;
    await this.reader?.cancel();
    await this.pump;
    await this.flush();
    this.writer.timed(this.timeline.finish());
    const report = await this.writer.close();
    this.closeEncoder();
    return report;
  }

  /** Encodes one sample; `starts` when it opens a segment. */
  protected abstract encode(sample: T, starts: boolean, seq: number): void;
  protected abstract flush(): Promise<void>;
  protected abstract closeEncoder(): void;
  protected abstract durationUs(sample: T): number;

  private async read(reader: ReadableStreamDefaultReader<T>): Promise<void> {
    while (this.running) {
      const { value: sample, done } = await reader.read();
      if (done || !sample) {
        return;
      }
      try {
        const placed = this.timeline.place(
          sample.timestamp,
          this.durationUs(sample),
          performance.now(),
        );
        this.writer.timed(placed.finished);
        if (placed.starts) {
          this.writer.started(sample.timestamp, placed.seq);
        }
        this.encode(sample, placed.starts, placed.seq);
      } finally {
        sample.close();
      }
    }
  }
}

/** The camera: H.264 MP4 (hardware first) or VP8 WebM, a keyframe at every segment start. */
export class CameraTrack extends WebCodecsTrack<VideoFrame> {
  private readonly encoder: VideoEncoder;

  private constructor(
    writer: SegmentWriter,
    ctx: RecordingContext,
    private readonly frameUs: number,
  ) {
    super("camera", writer, ctx);
    this.encoder = new VideoEncoder({
      output: (chunk, metadata) => writer.push(chunk, metadata?.decoderConfig),
      error: (error) => writer.fail(`video encoder: ${error.message}`),
    });
  }

  static async start(media: MediaStreamTrack, ctx: RecordingContext): Promise<CameraTrack> {
    const settings = media.getSettings();
    const h264: VideoEncoderConfig = {
      codec: H264_MAIN_31,
      width: settings.width ?? 1280,
      height: settings.height ?? 720,
      bitrate: ctx.videoBitrate,
      framerate: ctx.frameRate,
      hardwareAcceleration: "prefer-hardware",
      latencyMode: "realtime",
      avc: { format: "avc" },
    };
    let config = h264;
    let supported = (await VideoEncoder.isConfigSupported(h264)).supported === true;
    if (!supported) {
      config = { ...h264, hardwareAcceleration: "no-preference" };
      supported = (await VideoEncoder.isConfigSupported(config)).supported === true;
    }
    const format = chooseCameraFormat(supported);
    if (!supported) {
      const { avc: _avc, ...rest } = h264;
      config = { ...rest, codec: "vp8", hardwareAcceleration: "no-preference" };
    }
    const frameUs = 1_000_000 / ctx.frameRate;
    const writer = new SegmentWriter("video", "camera", format, ctx, 1 / ctx.frameRate);
    const camera = new CameraTrack(writer, ctx, frameUs);
    camera.encoder.configure(config);
    camera.begin(media);
    return camera;
  }

  protected encode(frame: VideoFrame, starts: boolean): void {
    if (!starts && this.encoder.encodeQueueSize > MAX_ENCODE_QUEUE) {
      this.writer.report.dropped += 1;
      return;
    }
    this.encoder.encode(frame, { keyFrame: starts });
  }

  protected durationUs(frame: VideoFrame): number {
    return frame.duration ?? this.frameUs;
  }

  protected async flush(): Promise<void> {
    if (this.encoder.state === "configured") {
      await this.encoder.flush();
    }
  }

  protected closeEncoder(): void {
    if (this.encoder.state !== "closed") {
      this.encoder.close();
    }
  }
}

/** The microphone: Opus in WebM. */
export class MicTrack extends WebCodecsTrack<AudioData> {
  private readonly encoder: AudioEncoder;

  private constructor(writer: SegmentWriter, ctx: RecordingContext) {
    super("mic", writer, ctx);
    this.encoder = new AudioEncoder({
      output: (chunk, metadata) => writer.push(chunk, metadata?.decoderConfig),
      error: (error) => writer.fail(`audio encoder: ${error.message}`),
    });
  }

  static async start(media: MediaStreamTrack, ctx: RecordingContext): Promise<MicTrack> {
    const settings = media.getSettings();
    const config: AudioEncoderConfig = {
      codec: "opus",
      sampleRate: settings.sampleRate ?? 48_000,
      numberOfChannels: settings.channelCount ?? 1,
      bitrate: ctx.audioBitrate,
    };
    if ((await AudioEncoder.isConfigSupported(config)).supported !== true) {
      throw new Error("this webview can't encode Opus");
    }
    const writer = new SegmentWriter("audio", "mic", MIC_OPUS, ctx, 0.02);
    const mic = new MicTrack(writer, ctx);
    mic.encoder.configure(config);
    mic.begin(media);
    return mic;
  }

  protected encode(data: AudioData): void {
    this.encoder.encode(data);
  }

  protected durationUs(data: AudioData): number {
    return data.duration;
  }

  protected async flush(): Promise<void> {
    if (this.encoder.state === "configured") {
      await this.encoder.flush();
    }
  }

  protected closeEncoder(): void {
    if (this.encoder.state !== "closed") {
      this.encoder.close();
    }
  }
}
