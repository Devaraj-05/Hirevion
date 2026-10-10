import {
  BufferTarget,
  EncodedAudioPacketSource,
  EncodedPacket,
  EncodedVideoPacketSource,
  Mp4OutputFormat,
  Output,
  WebMOutputFormat,
} from "mediabunny";
import type { Format } from "./formats";

type Chunk = EncodedVideoChunk | EncodedAudioChunk;

/**
 * One self-contained segment file (one video or one audio stream) built in memory with
 * Mediabunny. Its time zero is its first chunk, so every file plays on its own.
 */
export class SegmentFile {
  private readonly target = new BufferTarget();
  private readonly output: Output;
  private readonly video: EncodedVideoPacketSource | null = null;
  private readonly audio: EncodedAudioPacketSource | null = null;
  private configSent = false;
  private lastOffsetUs = -1;
  packets = 0;
  dropped = 0;

  constructor(
    kind: "video" | "audio",
    format: Format,
    readonly seq: number,
    /** The first chunk's timestamp (µs): time zero of this file. */
    readonly baseUs: number,
    /** Used when a chunk carries no duration (camera frames often don't). */
    private readonly fallbackDurationS: number,
  ) {
    this.output = new Output({
      format:
        format.container === "mp4"
          ? new Mp4OutputFormat({ fastStart: "in-memory" })
          : new WebMOutputFormat(),
      target: this.target,
    });
    if (kind === "video") {
      this.video = new EncodedVideoPacketSource(format.codec === "h264" ? "avc" : "vp8");
      this.output.addVideoTrack(this.video);
    } else {
      this.audio = new EncodedAudioPacketSource(format.codec === "aac" ? "aac" : "opus");
      this.output.addAudioTrack(this.audio);
    }
  }

  start(): Promise<void> {
    return this.output.start();
  }

  /** Adds a chunk; the first one must come with the decoder configuration. */
  async add(
    chunk: Chunk,
    config: VideoDecoderConfig | AudioDecoderConfig | undefined,
  ): Promise<void> {
    const offsetUs = chunk.timestamp - this.baseUs;
    if (offsetUs < 0 || offsetUs <= this.lastOffsetUs || (!this.configSent && !config)) {
      this.dropped += 1;
      return;
    }
    this.lastOffsetUs = offsetUs;
    const data = new Uint8Array(chunk.byteLength);
    chunk.copyTo(data);
    const duration = chunk.duration ? chunk.duration / 1_000_000 : this.fallbackDurationS;
    const packet = new EncodedPacket(data, chunk.type, offsetUs / 1_000_000, duration);
    const meta = !this.configSent && config ? { decoderConfig: config } : undefined;
    if (this.video) {
      await this.video.add(packet, meta as EncodedVideoChunkMetadata | undefined);
    } else if (this.audio) {
      await this.audio.add(packet, meta as EncodedAudioChunkMetadata | undefined);
    }
    this.configSent = true;
    this.packets += 1;
  }

  /** Finishes the file and returns its bytes. */
  async finish(): Promise<Uint8Array> {
    await this.output.finalize();
    const buffer = this.target.buffer;
    if (!buffer) {
      throw new Error(`segment ${this.seq} produced no data`);
    }
    return new Uint8Array(buffer);
  }
}
