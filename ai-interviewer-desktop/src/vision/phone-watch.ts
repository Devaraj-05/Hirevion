import type { FrameSource } from "./face-module";
import type { FromObjectWorker, ToObjectWorker } from "./object-worker";

/**
 * A phone in the main camera's picture (SP-15b; master plan §6.12 "phone and objects"). The
 * object detector is slow on a laptop's CPU (about 0.3 s a frame), so it looks once a second in
 * its own worker, never holding up the face module; the face module reads the latest answer.
 * Only the best phone score leaves the worker.
 */

export interface ObjectWorkerLike {
  postMessage(message: ToObjectWorker, transfer?: Transferable[]): void;
  onmessage: ((event: MessageEvent<FromObjectWorker>) => void) | null;
  terminate(): void;
}

export const PHONE_LABELS = ["cell phone"];
const LOOK_EVERY_MS = 1_000;
/** An answer older than this is stale: no claim either way. */
const FRESH_FOR_MS = 1_500;
/** A look the worker hasn't answered after this long is given up. */
const BUSY_TIMEOUT_MS = 3_000;

export function createObjectWorker(): ObjectWorkerLike {
  return new Worker(new URL("./object-worker.ts", import.meta.url), { type: "module" });
}

export class PhoneWatch {
  private timer: ReturnType<typeof setInterval> | undefined;
  private busySince: number | null = null;
  private latest: { score: number; at: number } | null = null;
  private stopped = false;

  constructor(
    private readonly source: FrameSource,
    private readonly worker: ObjectWorkerLike,
    private readonly now: () => number,
    private readonly onError: (message: string) => void = () => {},
  ) {
    this.worker.onmessage = (event) => this.onAnswer(event.data);
  }

  start(): void {
    if (this.stopped || this.timer) return;
    this.timer = setInterval(() => void this.look(), LOOK_EVERY_MS);
  }

  stop(): void {
    if (this.stopped) return;
    this.stopped = true;
    clearInterval(this.timer);
    this.worker.onmessage = null;
    this.worker.terminate();
  }

  /** The best phone score of the latest look, or null when there is no fresh one. */
  score(): number | null {
    if (!this.latest || this.now() - this.latest.at > FRESH_FOR_MS) return null;
    return this.latest.score;
  }

  async look(): Promise<void> {
    const now = this.now();
    if (this.stopped) return;
    if (this.busySince !== null && now - this.busySince < BUSY_TIMEOUT_MS) return;
    this.busySince = now;
    let bitmap: ImageBitmap | null = null;
    try {
      bitmap = await this.source.grab();
    } catch (error) {
      this.onError(`couldn't grab a frame for the phone check: ${String(error)}`);
    }
    if (!bitmap || this.stopped) {
      bitmap?.close();
      this.busySince = null;
      return;
    }
    this.worker.postMessage({ type: "frame", bitmap, at: now, labels: PHONE_LABELS }, [bitmap]);
  }

  private onAnswer(message: FromObjectWorker): void {
    this.busySince = null;
    if (message.type === "error") {
      this.onError(message.message);
      return;
    }
    const phones = message.detections.filter((found) => found.label === "cell phone");
    const score = phones.reduce((best, found) => Math.max(best, found.score), 0);
    this.latest = { score, at: this.now() };
  }
}
