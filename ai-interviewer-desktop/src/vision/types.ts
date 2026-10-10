/**
 * Shared shapes of the on-device face module (SP-15a). Times are monotonic milliseconds
 * (`performance.now()` on the main thread) until an event is built, which converts them to
 * server time through an injected clock.
 */

/** A detected face, normalised to the frame (0 to 1), with the detector's score. */
export interface FaceBox {
  x: number;
  y: number;
  width: number;
  height: number;
  score: number;
}

/**
 * Luminance statistics of a frame, each 0 to 1: the mean and standard deviation of luma, and
 * the mean absolute difference between neighbouring pixels (how much detail the frame holds).
 */
export interface FrameStats {
  meanLuma: number;
  stdLuma: number;
  edgeEnergy: number;
}

/** What the worker saw in one frame. `faces` is sorted best first. */
export interface FaceObservation {
  t: number;
  faces: FaceBox[];
  /** Null when the frame couldn't be measured. */
  frame: FrameStats | null;
}

/** The §56 signals the camera reports; "face present" is the normal state and has no event. */
export const CAMERA_SIGNALS = [
  "FACE_ABSENT",
  "MULTIPLE_FACES",
  "FACE_TOO_FAR",
  "FACE_TOO_CLOSE",
  "CAMERA_OBSTRUCTED",
] as const;

export type CameraSignal = (typeof CAMERA_SIGNALS)[number];

/** The client-side level an episode has crossed. The server still decides severity. */
export type Level = "warning" | "critical";

/** Where an episode is: it crossed its first threshold, crossed critical, or ended. */
export type Phase = "started" | "escalated" | "ended";

/** `proctoring.md`'s event sources. */
export type EventSource =
  | "camera"
  | "third_eye"
  | "screen"
  | "native"
  | "editor"
  | "audio"
  | "interview";

/** An evidence reference: `blob_path` comes from `POST /proctoring/evidence-uploads`. */
export interface EvidenceRef {
  type: string;
  blob_path: string;
}

/** One event of `POST /proctoring/events` (docs/api/contracts/proctoring.md). */
export interface ProctoringEvent {
  seq: number;
  event: string;
  source: EventSource;
  started_at: string;
  duration_ms: number;
  confidence: number;
  evidence: EvidenceRef[];
  details: Record<string, unknown>;
}

/** An event before the native queue numbers it. */
export type ProctoringEventDraft = Omit<ProctoringEvent, "seq">;

/** An episode's measurements: numbers only, never pixels or landmarks. */
export interface EpisodeDetails {
  /** Frames observed during the episode so far. */
  frames: number;
  /** MULTIPLE_FACES: the most faces seen in one frame. */
  max_faces?: number;
  /** FACE_TOO_FAR / FACE_TOO_CLOSE: the face box's mean height as a share of the frame. */
  face_height?: number;
  /** CAMERA_OBSTRUCTED: the frames' mean luma, 0 to 1. */
  mean_luma?: number;
}

/** What a camera event's `details` carries: the episode's phase and level, and its measurements. */
export interface CameraEventDetails extends EpisodeDetails {
  [key: string]: unknown;
  phase: Phase;
  level: Level;
}

/** A camera event as the face module emits it. */
export interface CameraEvent extends ProctoringEventDraft {
  event: CameraSignal;
  source: "camera";
  details: CameraEventDetails;
}
