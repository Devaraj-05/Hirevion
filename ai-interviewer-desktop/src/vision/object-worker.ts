// MediaPipe object detection off the UI thread, for the phone's picture (C8-3). Frames come in
// as ImageBitmaps and leave as labelled boxes; pixels never leave the device. The model is the
// bundled EfficientDet-Lite2 (COCO labels; only person, laptop and keyboard are kept): Lite0 gave
// a laptop seen from the side 0.13, Lite2 0.6-0.7 (owner's preview, 2026-11-16).
import { FilesetResolver, ObjectDetector } from "@mediapipe/tasks-vision";
import type { Detection } from "../third-eye/framing";

// As in face-worker.ts: development loads MediaPipe's WebAssembly from the package, builds from
// the copy in public/mediapipe.
const WASM_PATH = import.meta.env.DEV
  ? "/node_modules/@mediapipe/tasks-vision/wasm"
  : "/mediapipe/wasm";
const MODEL_PATH = "/models/efficientdet_lite2.tflite";

/**
 * `labels` picks the classes the detector keeps when it first loads: the placement check's
 * (the default) or the interview's phone check (SP-15b). One worker serves one of them.
 */
export type ToObjectWorker = {
  type: "frame";
  bitmap: ImageBitmap;
  at: number;
  labels?: string[];
};
const PLACEMENT_LABELS = ["person", "laptop", "keyboard"];
export type FromObjectWorker =
  | { type: "detections"; detections: Detection[]; width: number; height: number }
  | { type: "error"; message: string; fatal: boolean };

const scope = self as unknown as {
  postMessage(message: FromObjectWorker): void;
  onmessage: ((event: MessageEvent<ToObjectWorker>) => void) | null;
};

async function create(delegate: "GPU" | "CPU", labels: string[]): Promise<ObjectDetector> {
  const fileset = await FilesetResolver.forVisionTasks(WASM_PATH, true);
  return ObjectDetector.createFromOptions(fileset, {
    baseOptions: { modelAssetPath: MODEL_PATH, delegate },
    runningMode: "VIDEO",
    scoreThreshold: 0.3,
    maxResults: 10,
    categoryAllowlist: labels,
    canvas: new OffscreenCanvas(1, 1),
  });
}

// The CPU only: on the owner's laptop (and in headless Chromium) the GPU delegate loaded but
// returned no detections at all, so the check never saw anyone. About 0.3 s a frame on an i5.
function load(labels: string[]): Promise<ObjectDetector> {
  return create("CPU", labels);
}

let detector: Promise<ObjectDetector> | null = null;

scope.onmessage = async (event) => {
  const { bitmap, at, labels } = event.data;
  let ready: ObjectDetector;
  try {
    detector ??= load(labels ?? PLACEMENT_LABELS);
    ready = await detector;
  } catch (error) {
    // The model didn't start: say so (the screen offers to try again), and load afresh then.
    detector = null;
    bitmap.close();
    scope.postMessage({ type: "error", message: String(error), fatal: true });
    return;
  }
  try {
    const result = ready.detectForVideo(bitmap, at);
    const detections: Detection[] = result.detections.flatMap((found) => {
      const category = found.categories[0];
      const box = found.boundingBox;
      if (!category || !box) return [];
      return [
        {
          label: category.categoryName,
          score: category.score,
          box: { x: box.originX, y: box.originY, width: box.width, height: box.height },
        },
      ];
    });
    scope.postMessage({
      type: "detections",
      detections,
      width: bitmap.width,
      height: bitmap.height,
    });
  } catch (error) {
    scope.postMessage({ type: "error", message: String(error), fatal: false });
  } finally {
    bitmap.close();
  }
};
