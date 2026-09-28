import {
  BufferTarget,
  EncodedAudioPacketSource,
  EncodedPacket,
  EncodedVideoPacketSource,
  Mp4OutputFormat,
  Output,
} from "mediabunny";

/** One self-contained MP4 segment (H.264 video + Opus audio) built in memory. */
export class SegmentMuxer {
  readonly index: number;
  /** Capture timestamp (µs) that becomes time zero of this segment. */
  readonly baseUs: number;
  private readonly target = new BufferTarget();
  private readonly output = new Output({
    format: new Mp4OutputFormat({ fastStart: "in-memory" }),
    target: this.target,
  });
  private readonly video = new EncodedVideoPacketSource("avc");
  private readonly audio = new EncodedAudioPacketSource("opus");
  private videoConfigSent = false;
  private audioConfigSent = false;
  private lastAudioUs = -1;
  videoFrames = 0;
  audioChunks = 0;
  audioDropped = 0;

  constructor(
    index: number,
    baseUs: number,
    private readonly frameRate: number,
  ) {
    this.index = index;
    this.baseUs = baseUs;
    // No `frameRate` here: Mediabunny would snap timestamps to 1/15 s, and camera frames that
    // arrive a little early or late would then collide on the same timestamp.
    this.output.addVideoTrack(this.video);
    this.output.addAudioTrack(this.audio);
  }

  start(): Promise<void> {
    return this.output.start();
  }

  async addVideo(chunk: EncodedVideoChunk, config: VideoDecoderConfig | undefined): Promise<void> {
    // Camera frames often carry no duration; without one, the last frame of a segment would
    // end where it starts and joined segments would overlap.
    const packet = this.packet(chunk, chunk.timestamp - this.baseUs, 1 / this.frameRate);
    if (!this.videoConfigSent && config) {
      await this.video.add(packet, { decoderConfig: config });
      this.videoConfigSent = true;
    } else {
      await this.video.add(packet);
    }
    this.videoFrames += 1;
  }

  /** `timestampUs` is the chunk's time on the video clock (see CameraRecorder). */
  async addAudio(
    chunk: EncodedAudioChunk,
    config: AudioDecoderConfig | undefined,
    timestampUs: number,
  ): Promise<void> {
    const offsetUs = timestampUs - this.baseUs;
    // Audio from before this segment's first video frame, or out of order, is dropped.
    if (offsetUs < 0 || offsetUs <= this.lastAudioUs || (!this.audioConfigSent && !config)) {
      this.audioDropped += 1;
      return;
    }
    this.lastAudioUs = offsetUs;
    this.audioChunks += 1;
    const packet = this.packet(chunk, offsetUs, 0);
    if (!this.audioConfigSent && config) {
      await this.audio.add(packet, { decoderConfig: config });
      this.audioConfigSent = true;
    } else {
      await this.audio.add(packet);
    }
  }

  /** Finishes the file and returns its bytes. */
  async finish(): Promise<Uint8Array> {
    await this.output.finalize();
    const buffer = this.target.buffer;
    if (!buffer) {
      throw new Error(`segment ${this.index} produced no data`);
    }
    return new Uint8Array(buffer);
  }

  private packet(
    chunk: EncodedVideoChunk | EncodedAudioChunk,
    offsetUs: number,
    fallbackSeconds: number,
  ): EncodedPacket {
    const data = new Uint8Array(chunk.byteLength);
    chunk.copyTo(data);
    const duration = chunk.duration ? chunk.duration / 1_000_000 : fallbackSeconds;
    return new EncodedPacket(data, chunk.type, Math.max(0, offsetUs) / 1_000_000, duration);
  }
}
