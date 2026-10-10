import type { VisionConfig } from "./config";
import { isObstructedFrame } from "./frame-stats";
import type { CameraSignal, FaceObservation } from "./types";

/** Whether a signal's condition holds in one frame, and how sure the frame is of it (0 to 1). */
export interface SignalReading {
  on: boolean;
  confidence: number;
}

/** One frame, judged. */
export interface FrameReading {
  signals: Record<CameraSignal, SignalReading>;
  /** Faces that count: the best one, plus any second face that qualifies. */
  faces: number;
  /** The best face's height as a share of the frame; null without a face. */
  faceHeight: number | null;
  meanLuma: number | null;
}

/** No signal on: the state before the first frame. */
export const NO_SIGNALS: Readonly<Record<CameraSignal, boolean>> = {
  FACE_ABSENT: false,
  MULTIPLE_FACES: false,
  FACE_TOO_FAR: false,
  FACE_TOO_CLOSE: false,
  CAMERA_OBSTRUCTED: false,
};

const OFF: SignalReading = { on: false, confidence: 0 };

/**
 * Judges one frame for §56's signals. `wasOn` says which signals held in the previous frame:
 * a signal that held clears only past a wider bound (hysteresis).
 *
 * - No face: CAMERA_OBSTRUCTED when the frame is black or flat, else FACE_ABSENT.
 * - A second face scoring enough and big enough: MULTIPLE_FACES (distance isn't judged then).
 * - One face: FACE_TOO_FAR or FACE_TOO_CLOSE from its height.
 */
export function classifyFrame(
  observation: FaceObservation,
  config: VisionConfig,
  wasOn: Readonly<Record<CameraSignal, boolean>>,
): FrameReading {
  const signals: Record<CameraSignal, SignalReading> = {
    FACE_ABSENT: OFF,
    MULTIPLE_FACES: OFF,
    FACE_TOO_FAR: OFF,
    FACE_TOO_CLOSE: OFF,
    CAMERA_OBSTRUCTED: OFF,
  };
  const meanLuma = observation.frame?.meanLuma ?? null;
  const [primary, ...others] = observation.faces;
  if (!primary) {
    const obstructed =
      observation.frame !== null &&
      isObstructedFrame(observation.frame, config.obstruction, wasOn.CAMERA_OBSTRUCTED);
    signals[obstructed ? "CAMERA_OBSTRUCTED" : "FACE_ABSENT"] = { on: true, confidence: 1 };
    return { signals, faces: 0, faceHeight: null, meanLuma };
  }

  const { face } = config;
  const minScore = wasOn.MULTIPLE_FACES ? face.secondFaceStay : face.secondFaceEnter;
  const extra = others.filter(
    (other) => other.score >= minScore && other.height >= face.minFaceHeight,
  );
  const second = extra[0];
  if (second) {
    signals.MULTIPLE_FACES = { on: true, confidence: second.score };
  } else {
    const farBound = face.tooFarBelow + (wasOn.FACE_TOO_FAR ? face.sizeHysteresis : 0);
    const closeBound = face.tooCloseAbove - (wasOn.FACE_TOO_CLOSE ? face.sizeHysteresis : 0);
    if (primary.height < farBound) {
      signals.FACE_TOO_FAR = { on: true, confidence: primary.score };
    } else if (primary.height > closeBound) {
      signals.FACE_TOO_CLOSE = { on: true, confidence: primary.score };
    }
  }
  return { signals, faces: 1 + extra.length, faceHeight: primary.height, meanLuma };
}
