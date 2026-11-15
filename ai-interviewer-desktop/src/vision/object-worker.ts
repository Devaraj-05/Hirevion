// MediaPipe object detection off the UI thread, for the phone's picture (C8-3). Frames come in
// as ImageBitmaps and leave as labelled boxes; pixels never leave the device. The model is the
// bundled EfficientDet-Lite0 (COCO labels; only person, laptop and keyboard are kept).
import { FilesetResolver, ObjectDetector } from "@mediapipe/tasks-vision";
import type { Detection } from "../third-eye/framing";

// As in face-worker.ts: development loads MediaPipe's WebAssembly from the package, builds from
// the copy in public/mediapipe.
const WASM_PATH = import.meta.env.DEV
  ? "/node_modules/@mediapipe/tasks-vision/wasm"
  : "/mediapipe/wasm";
const MODEL_PATH = "/models/efficientdet_lite0.tflite";

export type ToObjectWorker = { type: "frame"; bitmap: ImageBitmap; at: number };
export type FromObjectWorker =
  | { type: "detections"; detections: Detection[]; width: number; height: number }
  | { type: "error"; message: string; fatal: boolean };

const scope = self as unknown as {
  postMessage(message: FromObjectWorker): void;
  onmessage: ((event: MessageEvent<ToObjectWorker>) => void) | null;
};

async function create(delegate: "GPU" | "CPU"): Promise<ObjectDetector> {
  const fileset = await FilesetResolver.forVisionTasks(WASM_PATH, true);
  return ObjectDetector.createFromOptions(fileset, {
    baseOptions: { modelAssetPath: MODEL_PATH, delegate },
    runningMode: "VIDEO",
    scoreThreshold: 0.3,
    maxResults: 10,
    categoryAllowlist: ["person", "laptop", "keyboard"],
    canvas: new OffscreenCanvas(1, 1),
  });
}

async function load(): Promise<ObjectDetector> {
  try {
    return await create("GPU");
  } catch {
    // WebGL unavailable or the GPU delegate failed: the CPU delegate is fine at 2 frames a second.
    return create("CPU");
  }
}

let detector: Promise<ObjectDetector> | null = null;

scope.onmessage = async (event) => {
  const { bitmap, at } = event.data;
  let ready: ObjectDetector;
  try {
    detector ??= load();
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
