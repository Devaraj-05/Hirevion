import type { Delegate, FromWorker, ToWorker } from "./face-worker";
import { FpsMeter, type Summary, summarize } from "./metrics";

export interface FaceReport {
  delegate: Delegate;
  targetFps: number;
  framesSent: number;
  framesSkipped: number;
  results: number;
  fps: number;
  inferenceMs: Summary | null;
  facesSeenRatio: number;
  errors: string[];
}

/** Sends video frames to the MediaPipe worker at a fixed rate, skipping while it is busy. */
export class FaceLoop {
  private readonly worker = new Worker(new URL("./face-worker.ts", import.meta.url), {
    type: "module",
  });
  private readonly meter = new FpsMeter(1_000);
  private readonly inference: number[] = [];
  private timer: number | undefined;
  private busy = false;
  private framesSent = 0;
  private framesSkipped = 0;
  private framesWithFace = 0;
  private lastFps = 0;
  private readonly errors: string[] = [];

  constructor(
    private readonly video: HTMLVideoElement,
    private readonly delegate: Delegate,
    private readonly targetFps: number,
  ) {}

  /** Loads the model, then starts sending frames. */
  start(): Promise<void> {
    return new Promise((resolve, reject) => {
      this.worker.onmessage = (event: MessageEvent<FromWorker>) => {
        const message = event.data;
        if (message.type === "ready") {
          this.timer = window.setInterval(() => void this.send(), 1_000 / this.targetFps);
          resolve();
        } else if (message.type === "error") {
          this.errors.push(message.message);
          reject(new Error(message.message));
        } else {
          this.busy = false;
          this.inference.push(message.inferenceMs);
          this.meter.tick(performance.now());
          this.lastFps = this.meter.fps(performance.now());
          if (message.faces > 0) {
            this.framesWithFace += 1;
          }
        }
      };
      this.post({ type: "init", delegate: this.delegate });
    });
  }

  /** Frames analysed per second over the last second. */
  get fps(): number {
    return this.lastFps;
  }

  stop(): FaceReport {
    window.clearInterval(this.timer);
    this.worker.terminate();
    const results = this.inference.length;
    return {
      delegate: this.delegate,
      targetFps: this.targetFps,
      framesSent: this.framesSent,
      framesSkipped: this.framesSkipped,
      results,
      fps: this.lastFps,
      inferenceMs: summarize(this.inference),
      facesSeenRatio: results === 0 ? 0 : this.framesWithFace / results,
      errors: this.errors,
    };
  }

  private async send(): Promise<void> {
    if (this.busy || this.video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) {
      this.framesSkipped += 1;
      return;
    }
    this.busy = true;
    const bitmap = await createImageBitmap(this.video);
    this.framesSent += 1;
    this.post({ type: "frame", bitmap, timestampMs: performance.now() }, [bitmap]);
  }

  private post(message: ToWorker, transfer: Transferable[] = []): void {
    this.worker.postMessage(message, transfer);
  }
}
