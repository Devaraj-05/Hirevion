import { messageOf, type RecordingContext, type TrackRecorder, type TrackReport } from "./context";
import { chooseRecorderFormat, type RecorderFormat, type WebviewTrack } from "./formats";
import { planRotation } from "./timing";

/**
 * The fallback when WebCodecs is missing: one `MediaRecorder` per track, replaced at every
 * window boundary so each file is complete and plays on its own. The next recorder starts
 * just before the previous one stops, so boundaries overlap by a few milliseconds instead of
 * leaving gaps. Start times are when each recorder reported it started (less precise than
 * WebCodecs, still well inside the 100 ms budget).
 */
export class RotatingRecorder implements TrackRecorder {
  private current: MediaRecorder | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private lastSeq = -1;
  private running = true;
  private readonly pending = new Set<Promise<void>>();
  private readonly report: TrackReport;

  private constructor(
    readonly track: WebviewTrack,
    private readonly media: MediaStreamTrack,
    private readonly format: RecorderFormat,
    private readonly ctx: RecordingContext,
  ) {
    this.report = {
      track,
      mode: "media-recorder",
      format: { container: format.container, codec: format.codec },
      segments: 0,
      bytes: 0,
      dropped: 0,
      errors: [],
    };
  }

  static start(
    track: WebviewTrack,
    media: MediaStreamTrack,
    ctx: RecordingContext,
  ): RotatingRecorder {
    const format = chooseRecorderFormat(track, (mime) => MediaRecorder.isTypeSupported(mime));
    if (!format) {
      throw new Error(`no MediaRecorder format for ${track}`);
    }
    const recorder = new RotatingRecorder(track, media, format, ctx);
    recorder.rotate();
    return recorder;
  }

  async stop(): Promise<TrackReport> {
    this.running = false;
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    const last = this.current;
    this.current = null;
    if (last && last.state !== "inactive") {
      last.stop();
    }
    while (this.pending.size > 0) {
      await Promise.all([...this.pending]);
    }
    return this.report;
  }

  /** Starts the next recorder, then stops the previous one. */
  private rotate(): void {
    if (!this.running) {
      return;
    }
    const previous = this.current;
    const { seq, stopInMs } = planRotation(
      this.ctx.time.nowMs(),
      this.ctx.planner.originServerMs,
      this.ctx.planner.segmentMs,
      this.lastSeq,
    );
    this.lastSeq = seq;
    this.current = this.record(seq);
    this.timer = setTimeout(() => this.rotate(), stopInMs);
    if (previous && previous.state !== "inactive") {
      previous.stop();
    }
  }

  private record(seq: number): MediaRecorder {
    const isVideo = this.track === "camera";
    const recorder = new MediaRecorder(new MediaStream([this.media]), {
      mimeType: this.format.recorderMime,
      ...(isVideo
        ? { videoBitsPerSecond: this.ctx.videoBitrate }
        : { audioBitsPerSecond: this.ctx.audioBitrate }),
    });
    const chunks: Blob[] = [];
    let startedAtMs = this.ctx.time.nowMs();
    let resolveDone: () => void = () => {};
    const done = new Promise<void>((resolve) => {
      resolveDone = resolve;
    });
    this.pending.add(done);
    recorder.onstart = () => {
      startedAtMs = this.ctx.time.nowMs();
    };
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        chunks.push(event.data);
      }
    };
    recorder.onerror = () => this.fail(`MediaRecorder failed in segment ${seq}`);
    recorder.onstop = () => {
      const durationMs = this.ctx.time.nowMs() - startedAtMs;
      void this.deliver(seq, startedAtMs, durationMs, chunks).finally(() => {
        this.pending.delete(done);
        resolveDone();
      });
    };
    recorder.start();
    return recorder;
  }

  private async deliver(
    seq: number,
    startedAtMs: number,
    durationMs: number,
    chunks: Blob[],
  ): Promise<void> {
    if (chunks.length === 0) {
      this.report.dropped += 1;
      return;
    }
    try {
      const bytes = new Uint8Array(await new Blob(chunks).arrayBuffer());
      await this.ctx.sink(
        {
          track: this.track,
          seq,
          startedAtMs,
          durationMs,
          container: this.format.container,
          codec: this.format.codec,
        },
        bytes,
      );
      this.report.segments += 1;
      this.report.bytes += bytes.byteLength;
    } catch (error) {
      this.fail(messageOf(error));
    }
  }

  private fail(message: string): void {
    this.report.errors.push(message);
    this.ctx.onError(this.track, message);
  }
}
