import enIN from "../i18n/en-IN.json";
import { classifyFrame, NO_SIGNALS } from "../vision/classify";
import { DEFAULT_VISION_CONFIG, type VisionConfig } from "../vision/config";
import { type FaceModuleOptions, startFaceModule } from "../vision/face-module";
import type { FaceObservation } from "../vision/types";
import type { CheckResult } from "./types";

/**
 * Face-quality guidance for the system check (SP-15a): one face, well lit, centred, at a good
 * distance. It folds into the existing `camera` check rather than adding a check name, since
 * the upload's names are fixed by interview-session.md and the screen labels them.
 */

/** In priority order: the first ones make proctoring impossible, the rest are advice. */
export const FACE_ISSUES = [
  "unavailable",
  "obstructed",
  "no_face",
  "multiple_faces",
  "too_dark",
  "too_far",
  "too_close",
  "off_centre",
] as const;

export type FaceIssue = (typeof FACE_ISSUES)[number];

export interface FaceGuidance {
  issues: FaceIssue[];
  /** Frames the guidance is based on. */
  frames: number;
}

export interface FaceGuidanceRules {
  /** Fewer frames than this and guidance is unavailable. */
  minFrames: number;
  /** An issue counts when at least this share of frames shows it. */
  issueShare: number;
  /** A frame darker than this (mean luma, 0 to 1) asks for more light. */
  darkBelow: number;
  /** How far the face's centre may sit from the frame's centre, as shares of the frame. */
  maxOffsetX: number;
  maxOffsetY: number;
}

export const DEFAULT_FACE_GUIDANCE: FaceGuidanceRules = {
  minFrames: 3,
  issueShare: 0.5,
  darkBelow: 0.25,
  maxOffsetX: 0.25,
  maxOffsetY: 0.3,
};

/** Without these the interview's face signals would fire at once, so they hold the check. */
export const BLOCKING_FACE_ISSUES: readonly FaceIssue[] = [
  "obstructed",
  "no_face",
  "multiple_faces",
];

/** The issues one frame shows, using the interview's own face rules. */
function frameIssues(
  observation: FaceObservation,
  config: VisionConfig,
  rules: FaceGuidanceRules,
): Set<FaceIssue> {
  const found = new Set<FaceIssue>();
  const { signals } = classifyFrame(observation, config, NO_SIGNALS);
  if (signals.CAMERA_OBSTRUCTED.on) {
    found.add("obstructed");
    return found;
  }
  if (signals.FACE_ABSENT.on) found.add("no_face");
  if (signals.MULTIPLE_FACES.on) found.add("multiple_faces");
  if (signals.FACE_TOO_FAR.on) found.add("too_far");
  if (signals.FACE_TOO_CLOSE.on) found.add("too_close");
  if (observation.frame && observation.frame.meanLuma < rules.darkBelow) found.add("too_dark");
  const primary = observation.faces[0];
  if (primary) {
    const offsetX = Math.abs(primary.x + primary.width / 2 - 0.5);
    const offsetY = Math.abs(primary.y + primary.height / 2 - 0.5);
    if (offsetX > rules.maxOffsetX || offsetY > rules.maxOffsetY) found.add("off_centre");
  }
  return found;
}

/** The issues shown by at least `issueShare` of the frames, in priority order. */
export function assessFace(
  observations: readonly FaceObservation[],
  config: VisionConfig = DEFAULT_VISION_CONFIG,
  rules: FaceGuidanceRules = DEFAULT_FACE_GUIDANCE,
): FaceGuidance {
  const frames = observations.length;
  if (frames < rules.minFrames) return { issues: ["unavailable"], frames };
  const counts = new Map<FaceIssue, number>();
  for (const observation of observations) {
    for (const issue of frameIssues(observation, config, rules)) {
      counts.set(issue, (counts.get(issue) ?? 0) + 1);
    }
  }
  const issues = FACE_ISSUES.filter(
    (issue) => (counts.get(issue) ?? 0) / frames >= rules.issueShare,
  );
  return { issues, frames };
}

/** The en-IN message for an issue (`vision.guidance`); the screen passes its translator instead. */
export function faceGuidanceText(issue: FaceIssue): string {
  return enIN.vision.guidance[issue];
}

export interface CameraGuidanceOptions {
  /** Issues that turn a passing camera into a warning; the policy may make them all advice. */
  blocking?: readonly FaceIssue[];
  describe?: (issue: FaceIssue) => string;
}

/**
 * The `camera` check with the face guidance in its `detail`. Obstructed, no face and several
 * faces turn a pass into a warning (the camera is mandatory, so the candidate fixes it and
 * checks again); lighting, distance and centring are advice only. A failed or skipped camera,
 * and unavailable guidance, leave the result as it was.
 */
export function cameraWithFaceGuidance(
  camera: CheckResult,
  guidance: FaceGuidance,
  options: CameraGuidanceOptions = {},
): CheckResult {
  const issues = guidance.issues.filter((issue) => issue !== "unavailable");
  if (camera.status === "fail" || camera.status === "skipped" || issues.length === 0) {
    return camera;
  }
  const blocking = options.blocking ?? BLOCKING_FACE_ISSUES;
  const describe = options.describe ?? faceGuidanceText;
  const advice = issues.map(describe).join(" ");
  const blocked = issues.some((issue) => blocking.includes(issue));
  return {
    ...camera,
    status: blocked && camera.status === "pass" ? "warn" : camera.status,
    detail: camera.detail ? `${camera.detail} ${advice}` : advice,
  };
}

export interface FaceSampleOptions
  extends Omit<FaceModuleOptions, "onObservation" | "onEvent" | "onStats"> {
  /** How long to watch; guidance covers the last `windowMs` of it. */
  durationMs?: number;
  windowMs?: number;
  /** Live guidance for the camera preview, after each frame. */
  onGuidance?: (guidance: FaceGuidance) => void;
}

/**
 * Watches the camera preview for about 2 s and returns the guidance for the latest frames.
 * Raises no proctoring events: the system check isn't proctored. Resolves to "unavailable"
 * when the face module can't start, so the check never blocks on it.
 */
export async function sampleFaceGuidance(options: FaceSampleOptions): Promise<FaceGuidance> {
  const { durationMs = 2_000, windowMs = 2_000, onGuidance, ...moduleOptions } = options;
  const seen: FaceObservation[] = [];
  const recent = () => {
    const latest = seen.at(-1)?.t ?? 0;
    return seen.filter((observation) => observation.t >= latest - windowMs);
  };
  try {
    const module = await startFaceModule({
      ...moduleOptions,
      onObservation: (observation) => {
        seen.push(observation);
        onGuidance?.(assessFace(recent()));
      },
    });
    await new Promise((resolve) => setTimeout(resolve, durationMs));
    module.stop();
  } catch {
    return { issues: ["unavailable"], frames: 0 };
  }
  return assessFace(recent());
}
