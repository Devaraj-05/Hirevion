import { DEFAULT_VISION_CONFIG, type VisionConfig } from "./config";
import { type ServerClock, SignalEngine } from "./engine";
import {
  DEFAULT_FRAME_RATE,
  type FrameRateConfig,
  type FrameRateState,
  initialFrameRate,
  nextFrameRate,
} from "./frame-rate";
import { FpsMeter, type Summary, summarize } from "./metrics";
import type { Delegate, FromWorker, ToWorker } from "./protocol";
import type { CameraEvent, CameraSignal, FaceObservation } from "./types";

/** Where frames come from: the camera preview in the app, a recorded clip when evaluating. */
export interface FrameSource {
  /** A frame to analyse, or null when none is ready. The module transfers it to the worker. */
  grab(): Promise<ImageBitmap | null>;
}

/**
 * Frames from a playing `<video>`, shrunk to at most `maxWidth` (the detector's input is
 * 128x128, so full HD buys nothing but copying).
 */
export function videoFrameSource(video: HTMLVideoElement, maxWidth = 640): FrameSource {
  return {
    async grab() {
      if (video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA || video.videoWidth === 0) {
        return null;
      }
      if (video.videoWidth <= maxWidth) return createImageBitmap(video);
      return createImageBitmap(video, { resizeWidth: maxWidth, resizeQuality: "low" });
    },
  };
}

/** What the module needs of a `Worker`; tests pass a fake. */
export interface WorkerLike {
  postMessage(message: ToWorker, transfer?: Transferable[]): void;
  onmessage: ((event: MessageEvent<FromWorker>) => void) | null;
  onerror: ((event: ErrorEvent) => void) | null;
  terminate(): void;
}

/** For the heartbeat's `vision_fps` and the CPU-budget check. */
export interface VisionStats {
  delegate: Delegate | null;
  /** The rate the adaptive controller asks for, and the rate measured over the last second. */
  targetFps: number;
  fps: number;
  /** The worker's detection time over the last 100 frames. */
  inferenceMs: Summary | null;
  framesAnalysed: number;
  framesSkipped: number;
  /** True when even the lowest rate doesn't fit the CPU budget. */
  overBudget: boolean;
}

export interface FaceModuleOptions {
  source: FrameSource;
  /** From `visionConfigFromPolicy(session)`; the defaults otherwise. */
  config?: VisionConfig;
  frameRate?: FrameRateConfig;
  /** Preferred delegate; the worker falls back to CPU. */
  delegate?: Delegate;
  /** Each event, without `seq`: SP-08b forwards it to the native queue. */
  onEvent?: (event: CameraEvent) => void;
  /** Each frame's boxes and luminance: the system check's guidance, and clip recording. */
  onObservation?: (observation: FaceObservation) => void;
  /** Once a second. */
  onStats?: (stats: VisionStats) => void;
  onError?: (message: string) => void;
  /** Monotonic time → server-time ISO for `started_at`; the local clock otherwise. */
  toServerIso?: ServerClock;
  createWorker?: () => WorkerLike;
  /** Monotonic milliseconds; `performance.now()` otherwise. */
  now?: () => number;
}

/** A frame the worker hasn't answered after this long is given up. */
const BUSY_TIMEOUT_MS = 2_000;
const STATS_INTERVAL_MS = 1_000;
const INFERENCE_SAMPLES = 100;
/** The detector's own score floor; the rule engine applies stricter ones per signal. */
const MIN_DETECTION_CONFIDENCE = 0.5;

function createFaceWorker(): WorkerLike {
  return new Worker(new URL("./face-worker.ts", import.meta.url), { type: "module" });
}

/**
 * Starts the on-device face module: loads MediaPipe in a worker, then analyses frames at the
 * adaptive rate (5–10 fps), skipping while the worker is busy, and feeds the rule engine.
 * Resolves once the model is loaded; rejects when neither delegate can load it.
 */
export function startFaceModule(options: FaceModuleOptions): Promise<FaceModule> {
  const module = new FaceModule(options);
  return module.ready.then(() => module);
}

export class FaceModule {
  /** Settles when the worker has loaded the model (or failed to). */
  readonly ready: Promise<void>;
  private readonly worker: WorkerLike;
  private readonly engine: SignalEngine;
  private readonly frameRateConfig: FrameRateConfig;
  private readonly now: () => number;
  private readonly meter = new FpsMeter(1_000);
  private readonly inference: number[] = [];
  private frameRate: FrameRateState;
  private delegate: Delegate | null = null;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private statsTimer: ReturnType<typeof setInterval> | undefined;
  private busySince: number | null = null;
  private framesAnalysed = 0;
  private framesSkipped = 0;
  private stopped = false;

  constructor(private readonly options: FaceModuleOptions) {
    this.now = options.now ?? (() => performance.now());
    this.frameRateConfig = options.frameRate ?? DEFAULT_FRAME_RATE;
    this.frameRate = initialFrameRate(this.frameRateConfig);
    const engineOptions: ConstructorParameters<typeof SignalEngine>[1] = {};
    if (options.onEvent) engineOptions.onEvent = options.onEvent;
    if (options.toServerIso) engineOptions.toServerIso = options.toServerIso;
    this.engine = new SignalEngine(options.config ?? DEFAULT_VISION_CONFIG, engineOptions);
    this.worker = (options.createWorker ?? createFaceWorker)();
    this.ready = new Promise((resolve, reject) => {
      this.worker.onmessage = (event) => {
        const message = event.data;
        if (message.type === "ready") {
          const first = this.delegate === null;
          this.delegate = message.delegate;
          if (first) {
            this.begin();
            resolve();
          }
        } else if (message.type === "error") {
          this.busySince = null;
          if (this.delegate === null) {
            this.stop();
            reject(new Error(message.message));
          } else {
            this.options.onError?.(message.message);
          }
        } else {
          this.onResult(message);
        }
      };
      this.worker.onerror = (event) => {
        const message = event.message || "the face worker failed";
        if (this.delegate === null) {
          this.stop();
          reject(new Error(message));
        } else {
          this.options.onError?.(message);
        }
      };
    });
    this.post({
      type: "init",
      model: "face_detector",
      delegate: options.delegate ?? "GPU",
      minDetectionConfidence: MIN_DETECTION_CONFIDENCE,
      statsWidth: 32,
      statsHeight: 24,
    });
  }

  stats(): VisionStats {
    return {
      delegate: this.delegate,
      targetFps: this.frameRate.fps,
      fps: this.meter.fps(this.now()),
      inferenceMs: summarize(this.inference),
      framesAnalysed: this.framesAnalysed,
      framesSkipped: this.framesSkipped,
      overBudget: this.frameRate.overBudget,
    };
  }

  /** The signals currently reported, e.g. to nudge the candidate. */
  active(): CameraSignal[] {
    return this.engine.active();
  }

  /** Ends open episodes (their `ended` events are emitted), stops sampling and the worker. */
  stop(): void {
    if (this.stopped) return;
    this.stopped = true;
    clearTimeout(this.timer);
    clearInterval(this.statsTimer);
    this.worker.onmessage = null;
    this.worker.terminate();
    this.engine.flush();
  }

  private begin(): void {
    if (this.stopped) return;
    this.schedule();
    this.statsTimer = setInterval(() => this.options.onStats?.(this.stats()), STATS_INTERVAL_MS);
  }

  private schedule(): void {
    if (this.stopped) return;
    this.timer = setTimeout(() => void this.tick(), 1_000 / this.frameRate.fps);
  }

  private async tick(): Promise<void> {
    this.schedule();
    const now = this.now();
    if (this.busySince !== null) {
      if (now - this.busySince < BUSY_TIMEOUT_MS) {
        this.framesSkipped += 1;
        return;
      }
      this.busySince = null;
      this.options.onError?.(`the face worker didn't answer within ${BUSY_TIMEOUT_MS} ms`);
    }
    this.busySince = now;
    let bitmap: ImageBitmap | null = null;
    try {
      bitmap = await this.options.source.grab();
    } catch (error) {
      this.options.onError?.(`couldn't grab a frame: ${String(error)}`);
    }
    if (!bitmap || this.stopped) {
      bitmap?.close();
      this.busySince = null;
      this.framesSkipped += 1;
      return;
    }
    this.post({ type: "frame", bitmap, t: this.now() }, [bitmap]);
  }

  private onResult(message: Extract<FromWorker, { type: "result" }>): void {
    this.busySince = null;
    const now = this.now();
    this.framesAnalysed += 1;
    this.meter.tick(now);
    this.inference.push(message.inferenceMs);
    if (this.inference.length > INFERENCE_SAMPLES) this.inference.shift();
    this.frameRate = nextFrameRate(this.frameRate, message.processingMs, now, this.frameRateConfig);
    const observation: FaceObservation = {
      t: message.t,
      faces: message.faces,
      frame: message.frame,
    };
    this.engine.push(observation);
    this.options.onObservation?.(observation);
  }

  private post(message: ToWorker, transfer: Transferable[] = []): void {
    this.worker.postMessage(message, transfer);
  }
}
