// MediaPipe face detection off the UI thread (ADR-0007). See protocol.ts for the messages.
// Each frame yields normalised face boxes plus luminance statistics from a 32x24 copy; pixels
// never leave the worker. No eval: MediaPipe's WebAssembly needs only 'wasm-unsafe-eval'.
import { FaceDetector, FilesetResolver } from "@mediapipe/tasks-vision";
import { toFaceBoxes } from "./detections";
import { frameStats } from "./frame-stats";
import type { Delegate, FromWorker, ToWorker } from "./protocol";

// Vite's dev server refuses dynamic imports of files in public/, which is how MediaPipe loads
// its WebAssembly loader; development therefore loads it from the package, and builds use the
// copy that scripts/copy-mediapipe.mjs puts in public/mediapipe.
const WASM_PATH = import.meta.env.DEV
  ? "/node_modules/@mediapipe/tasks-vision/wasm"
  : "/mediapipe/wasm";
const MODEL_PATH = "/models/blaze_face_short_range.tflite";

// The DOM typings describe `self` as a Window; in a dedicated worker it is the worker scope.
const scope = self as unknown as {
  postMessage(message: FromWorker): void;
  onmessage: ((event: MessageEvent<ToWorker>) => void) | null;
};

type Init = Extract<ToWorker, { type: "init" }>;

let settings: Init | null = null;
let detector: FaceDetector | null = null;
let delegate: Delegate = "GPU";
let stats: OffscreenCanvasRenderingContext2D | null = null;
let switching = false;

async function create(wanted: Delegate, minDetectionConfidence: number): Promise<FaceDetector> {
  const fileset = await FilesetResolver.forVisionTasks(WASM_PATH, true);
  return FaceDetector.createFromOptions(fileset, {
    baseOptions: { modelAssetPath: MODEL_PATH, delegate: wanted },
    runningMode: "VIDEO",
    minDetectionConfidence,
    canvas: new OffscreenCanvas(1, 1),
  });
}

/** Loads the model on the wanted delegate, falling back to CPU when GPU fails. */
async function load(wanted: Delegate, minDetectionConfidence: number): Promise<Delegate> {
  if (wanted === "GPU") {
    try {
      detector = await create("GPU", minDetectionConfidence);
      return "GPU";
    } catch {
      // WebGL unavailable or the GPU delegate failed: the CPU delegate is a close second.
    }
  }
  detector = await create("CPU", minDetectionConfidence);
  return "CPU";
}

/** After a GPU failure mid-session (e.g. a lost WebGL context), moves to CPU once. */
async function fallBackToCpu(reason: unknown): Promise<void> {
  if (switching || !settings) return;
  switching = true;
  detector?.close();
  detector = null;
  try {
    delegate = await load("CPU", settings.minDetectionConfidence);
    scope.postMessage({ type: "ready", delegate });
  } catch (error) {
    scope.postMessage({ type: "error", message: String(error ?? reason), fatal: true });
  } finally {
    switching = false;
  }
}

function measure(bitmap: ImageBitmap, init: Init) {
  if (!stats) {
    stats = new OffscreenCanvas(init.statsWidth, init.statsHeight).getContext("2d", {
      willReadFrequently: true,
    });
  }
  if (!stats) return null;
  stats.drawImage(bitmap, 0, 0, init.statsWidth, init.statsHeight);
  const pixels = stats.getImageData(0, 0, init.statsWidth, init.statsHeight);
  return frameStats(pixels.data, init.statsWidth, init.statsHeight);
}

function analyse(bitmap: ImageBitmap, t: number): void {
  const init = settings;
  if (!detector || !init) {
    scope.postMessage({ type: "error", message: "the face detector isn't loaded", fatal: false });
    return;
  }
  const started = performance.now();
  try {
    const frame = measure(bitmap, init);
    const detecting = performance.now();
    const result = detector.detectForVideo(bitmap, t);
    const done = performance.now();
    scope.postMessage({
      type: "result",
      t,
      faces: toFaceBoxes(result.detections, bitmap.width, bitmap.height),
      frame,
      inferenceMs: done - detecting,
      processingMs: done - started,
    });
  } catch (error) {
    scope.postMessage({ type: "error", message: String(error), fatal: false });
    if (delegate === "GPU") void fallBackToCpu(error);
  }
}

scope.onmessage = (event) => {
  const message = event.data;
  if (message.type === "init") {
    settings = message;
    load(message.delegate, message.minDetectionConfidence).then(
      (loaded) => {
        delegate = loaded;
        scope.postMessage({ type: "ready", delegate });
      },
      (error: unknown) => scope.postMessage({ type: "error", message: String(error), fatal: true }),
    );
    return;
  }
  try {
    analyse(message.bitmap, message.t);
  } finally {
    message.bitmap.close();
  }
};
