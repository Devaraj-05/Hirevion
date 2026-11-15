import type { FrameSource } from "../vision/face-module";
import type { FromObjectWorker, ToObjectWorker } from "../vision/object-worker";
import type { Detection } from "./framing";

/** One analysed frame of the phone's picture. */
export interface Seen {
  detections: Detection[];
  width: number;
  height: number;
}

/** What the detector needs of a `Worker`; tests pass a fake. */
export interface DetectorWorker {
  postMessage(message: ToObjectWorker, transfer?: Transferable[]): void;
  onmessage: ((event: MessageEvent<FromObjectWorker>) => void) | null;
  onerror: ((event: ErrorEvent) => void) | null;
  terminate(): void;
}

/** How long a frame may take before it is given up on (as face-module.ts). */
const BUSY_TIMEOUT_MS = 2_000;
/** Frames lost in a row (errors or no answer) before the check counts as failed. */
export const FAIL_AFTER = 5;

function objectWorker(): DetectorWorker {
  return new Worker(new URL("../vision/object-worker.ts", import.meta.url), { type: "module" });
}

/**
 * Runs the object detector in a worker on frames of the phone's picture (C8-3): one frame at a
 * time, so a slow device skips frames instead of queueing them. A worker that doesn't answer,
 * or keeps failing, makes the check `failed`, so the screen can say so instead of waiting.
 */
export class PlacementDetector {
  private pending: ((seen: Seen | null) => void) | null = null;
  private busySince: number | null = null;
  private lost = 0;
  private fatal = false;

  constructor(
    private readonly worker: DetectorWorker = objectWorker(),
    private readonly now: () => number = () => performance.now(),
  ) {
    worker.onmessage = (event) => {
      const data = event.data;
      if (data.type === "detections") this.settle(data);
      else {
        if (data.fatal) this.fatal = true;
        this.settle(null);
      }
    };
    worker.onerror = () => {
      this.fatal = true;
      this.settle(null);
    };
  }

  /** The check can't run here (the model didn't start, or frames keep getting lost). */
  get failed(): boolean {
    return this.fatal || this.lost >= FAIL_AFTER;
  }

  /** The detections in the source's current frame; `null` when busy, not playing, or lost. */
  async detect(source: FrameSource): Promise<Seen | null> {
    const now = this.now();
    if (this.busySince !== null) {
      if (now - this.busySince < BUSY_TIMEOUT_MS) return null;
      this.settle(null); // the worker never answered that frame
    }
    // Failed for good: the screen says so, and "Try again" makes a new detector.
    if (this.failed) return null;
    this.busySince = now;
    let bitmap: ImageBitmap | null = null;
    try {
      bitmap = await source.grab();
    } catch {
      bitmap = null;
    }
    if (!bitmap) {
      this.busySince = null;
      return null;
    }
    const frame = bitmap;
    return new Promise((resolve) => {
      this.pending = resolve;
      this.worker.postMessage({ type: "frame", bitmap: frame, at: now }, [frame]);
    });
  }

  close(): void {
    this.worker.terminate();
    this.settle(null);
  }

  private settle(seen: Seen | null): void {
    const resolve = this.pending;
    const waiting = this.busySince !== null;
    this.pending = null;
    this.busySince = null;
    if (seen) this.lost = 0;
    else if (waiting) this.lost += 1;
    resolve?.(seen);
  }
}
