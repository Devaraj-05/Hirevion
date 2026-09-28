// MediaPipe face detection off the UI thread. Messages:
//   in:  { type: "init", delegate: "GPU" | "CPU" }  then  { type: "frame", bitmap, timestampMs }
//   out: { type: "ready" } | { type: "error", message } | { type: "result", faces, inferenceMs }
import { FaceDetector, FilesetResolver } from "@mediapipe/tasks-vision";

export type Delegate = "GPU" | "CPU";

export type ToWorker =
  | { type: "init"; delegate: Delegate }
  | { type: "frame"; bitmap: ImageBitmap; timestampMs: number };

export type FromWorker =
  | { type: "ready" }
  | { type: "error"; message: string }
  | { type: "result"; faces: number; inferenceMs: number };

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

let detector: FaceDetector | null = null;

async function init(delegate: Delegate): Promise<void> {
  const fileset = await FilesetResolver.forVisionTasks(WASM_PATH, true);
  detector = await FaceDetector.createFromOptions(fileset, {
    baseOptions: { modelAssetPath: MODEL_PATH, delegate },
    runningMode: "VIDEO",
    minDetectionConfidence: 0.5,
    canvas: new OffscreenCanvas(1, 1),
  });
}

scope.onmessage = (event) => {
  const message = event.data;
  if (message.type === "init") {
    init(message.delegate).then(
      () => scope.postMessage({ type: "ready" }),
      (error: unknown) => scope.postMessage({ type: "error", message: String(error) }),
    );
    return;
  }
  if (!detector) {
    message.bitmap.close();
    return;
  }
  const started = performance.now();
  const result = detector.detectForVideo(message.bitmap, message.timestampMs);
  const inferenceMs = performance.now() - started;
  message.bitmap.close();
  scope.postMessage({ type: "result", faces: result.detections.length, inferenceMs });
};
