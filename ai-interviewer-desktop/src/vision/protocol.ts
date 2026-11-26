import type { GazeReading } from "./gaze";
import type { FaceBox, FrameStats } from "./types";

/** MediaPipe's delegates: GPU (WebGL on an OffscreenCanvas) first, CPU (WebAssembly) as fallback. */
export type Delegate = "GPU" | "CPU";

/** The models the worker can run. SP-15b adds the face landmarker for gaze. */
export type VisionModel = "face_detector";

/** Main thread → worker. */
export type ToWorker =
  | {
      type: "init";
      model: VisionModel;
      /** Preferred; the worker falls back to CPU when GPU fails. */
      delegate: Delegate;
      minDetectionConfidence: number;
      /** The size the frame is shrunk to for its luminance statistics. */
      statsWidth: number;
      statsHeight: number;
      /** SP-15b: also run the face landmarker for gaze (with one face, at most ~7 times a second). */
      gaze?: boolean;
    }
  | { type: "frame"; bitmap: ImageBitmap; t: number };

/** Worker → main thread. Only boxes and numbers leave the worker: never pixels. */
export type FromWorker =
  | { type: "ready"; delegate: Delegate }
  | { type: "error"; message: string; fatal: boolean }
  /** Something optional stopped (gaze): the face module carries on (review, 2026-11-26). */
  | { type: "warning"; message: string }
  | {
      type: "result";
      t: number;
      faces: FaceBox[];
      frame: FrameStats | null;
      /** SP-15b: the one face's head turn and eye direction, when the landmarker ran. */
      gaze?: GazeReading | null;
      /** Detection alone, and detection plus the luminance statistics. */
      inferenceMs: number;
      processingMs: number;
    };
