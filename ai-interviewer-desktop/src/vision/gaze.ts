/**
 * Where the candidate looks (SP-15b, PRD §57): frame → face → landmarks → eyes → gaze → temporal
 * smoothing → event. MediaPipe's face landmarker gives 478 landmarks and ARKit-style eye
 * blendshapes; this turns them into four numbers and a direction. Only the numbers leave the
 * worker, never the landmarks; the direction is judged against this candidate's own resting
 * pose (the first readings), because a webcam above the screen makes "looking at the screen" a
 * slight downward look. Gaze is a signal, never proof (§57): it is information until it lasts,
 * a warning after 10 s, and never critical on its own (the server's rules).
 */

/** Head turn and eye direction from one frame. */
export interface GazeReading {
  /** The nose's place between the cheeks, -0.5 to 0.5: positive is the candidate's left. */
  yaw: number;
  /** The nose's place from the eye line to the chin, 0 to 1: larger is the head bent down. */
  pitch: number;
  /** Eyes' horizontal look, -1 to 1: positive is the candidate's left. */
  eyeX: number;
  /** Eyes' vertical look, -1 to 1: positive is down. */
  eyeY: number;
}

export type GazeDirection = "center" | "left" | "right" | "down";

/** How far from the resting pose counts as looking away, before and while it holds. */
export interface GazeRules {
  yaw: number;
  pitchDown: number;
  eye: number;
  /** Once away, the bounds are multiplied by this to come back (hysteresis). */
  hysteresis: number;
}

export const DEFAULT_GAZE_RULES: GazeRules = {
  yaw: 0.12,
  pitchDown: 0.1,
  eye: 0.4,
  hysteresis: 0.8,
};

export interface Point {
  x: number;
  y: number;
}

export interface Blendshape {
  categoryName: string;
  score: number;
}

// MediaPipe face mesh indices: nose tip, the cheeks (the picture's left and right), the outer eye
// corners, the chin.
const NOSE = 1;
const CHEEK_A = 234;
const CHEEK_B = 454;
const EYE_A = 33;
const EYE_B = 263;
const CHIN = 152;

function score(shapes: readonly Blendshape[], name: string): number {
  return shapes.find((shape) => shape.categoryName === name)?.score ?? 0;
}

/** The reading for one face, or null when its landmarks are missing or degenerate. */
export function readingFromLandmarks(
  landmarks: readonly Point[],
  blendshapes: readonly Blendshape[],
): GazeReading | null {
  const nose = landmarks[NOSE];
  const a = landmarks[CHEEK_A];
  const b = landmarks[CHEEK_B];
  const eyeA = landmarks[EYE_A];
  const eyeB = landmarks[EYE_B];
  const chin = landmarks[CHIN];
  if (!nose || !a || !b || !eyeA || !eyeB || !chin) return null;
  const width = b.x - a.x;
  const eyeLine = (eyeA.y + eyeB.y) / 2;
  const height = chin.y - eyeLine;
  if (Math.abs(width) < 1e-3 || height < 1e-3) return null;
  const left = score(blendshapes, "eyeLookOutLeft") + score(blendshapes, "eyeLookInRight");
  const right = score(blendshapes, "eyeLookInLeft") + score(blendshapes, "eyeLookOutRight");
  const down = score(blendshapes, "eyeLookDownLeft") + score(blendshapes, "eyeLookDownRight");
  const up = score(blendshapes, "eyeLookUpLeft") + score(blendshapes, "eyeLookUpRight");
  return {
    yaw: (nose.x - a.x) / width - 0.5,
    pitch: (nose.y - eyeLine) / height,
    eyeX: (left - right) / 2,
    eyeY: (down - up) / 2,
  };
}

/**
 * The direction of one reading against the resting pose. `wasAway` widens the way back, so a
 * look held near the bound doesn't flicker. Sideways wins over down when both hold.
 */
export function gazeDirection(
  reading: GazeReading,
  rest: GazeReading,
  rules: GazeRules,
  wasAway: boolean,
): GazeDirection {
  const scale = wasAway ? rules.hysteresis : 1;
  const yaw = reading.yaw - rest.yaw;
  const eyeX = reading.eyeX - rest.eyeX;
  if (yaw > rules.yaw * scale || eyeX > rules.eye * scale) return "left";
  if (yaw < -rules.yaw * scale || eyeX < -rules.eye * scale) return "right";
  const pitch = reading.pitch - rest.pitch;
  const eyeY = reading.eyeY - rest.eyeY;
  if (pitch > rules.pitchDown * scale || eyeY > rules.eye * scale) return "down";
  return "center";
}

const median = (values: number[]): number => {
  const sorted = [...values].sort((x, y) => x - y);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2
    ? (sorted[middle] ?? 0)
    : ((sorted[middle - 1] ?? 0) + (sorted[middle] ?? 0)) / 2;
};

/**
 * The candidate's resting pose: the median of the first `size` readings (about ten seconds at
 * the landmarker's rate), when they are looking at the screen to start the interview.
 */
export class GazeBaseline {
  private readonly readings: GazeReading[] = [];
  private rest: GazeReading | null = null;

  constructor(private readonly size = 40) {}

  add(reading: GazeReading): void {
    if (this.rest) return;
    this.readings.push(reading);
    if (this.readings.length < this.size) return;
    this.rest = {
      yaw: median(this.readings.map((r) => r.yaw)),
      pitch: median(this.readings.map((r) => r.pitch)),
      eyeX: median(this.readings.map((r) => r.eyeX)),
      eyeY: median(this.readings.map((r) => r.eyeY)),
    };
  }

  value(): GazeReading | null {
    return this.rest;
  }
}
