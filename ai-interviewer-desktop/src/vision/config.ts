import { CAMERA_SIGNALS, type CameraSignal, type Level } from "./types";

/**
 * When a signal is reported, in the proctor session's spelling (`proctoring.md`'s
 * `thresholds`). A level without a value is never reached; a signal with neither raises nothing.
 */
export interface SignalRule {
  warn_after_ms?: number;
  critical_after_ms?: number;
}

/** Face-box rules, as shares of the frame height and detector scores. */
export interface FaceRules {
  /** A second face counts from this height, so a speck isn't a person. */
  minFaceHeight: number;
  /** The second face's score that starts MULTIPLE_FACES, and the one that keeps it. */
  secondFaceEnter: number;
  secondFaceStay: number;
  /** FACE_TOO_FAR below this face height; FACE_TOO_CLOSE above the other. */
  tooFarBelow: number;
  tooCloseAbove: number;
  /** How far back across a bound a face must come to clear a distance signal. */
  sizeHysteresis: number;
}

/** Luma (0 to 1) below which a frame is black, and the spread and detail below which it's flat. */
export interface ObstructionRules {
  darkBelow: number;
  flatStdBelow: number;
  flatEdgeBelow: number;
  /** Once obstructed, the bounds are multiplied by this to clear it. */
  hysteresis: number;
}

export interface VisionConfig {
  signals: Record<CameraSignal, SignalRule>;
  face: FaceRules;
  obstruction: ObstructionRules;
  /** A condition must be gone this long to end an episode, so a missed frame doesn't. */
  clearAfterMs: number;
  /**
   * A condition holds when it held in most of the last this many frames (a majority filter),
   * so sparse detector mistakes neither start nor sustain an episode.
   */
  smoothingFrames: number;
  /** With no frame for this long, open episodes end at the last frame. */
  maxGapMs: number;
}

/**
 * Master plan §6.12's table for absence, multiple faces and obstruction. Distance has no row:
 * it warns after 10 s (SP-15a plan). Bounds measured for a 16:9 webcam with a ~70° field of
 * view: a face box of 15 % of the frame height is about 1.5 m away, 65 % about 35 cm.
 */
export const DEFAULT_VISION_CONFIG: VisionConfig = {
  signals: {
    FACE_ABSENT: { warn_after_ms: 5_000, critical_after_ms: 30_000 },
    MULTIPLE_FACES: { critical_after_ms: 3_000 },
    FACE_TOO_FAR: { warn_after_ms: 10_000 },
    FACE_TOO_CLOSE: { warn_after_ms: 10_000 },
    CAMERA_OBSTRUCTED: { critical_after_ms: 5_000 },
  },
  face: {
    minFaceHeight: 0.05,
    secondFaceEnter: 0.6,
    secondFaceStay: 0.5,
    tooFarBelow: 0.15,
    tooCloseAbove: 0.65,
    sizeHysteresis: 0.02,
  },
  obstruction: {
    darkBelow: 0.06,
    flatStdBelow: 0.03,
    flatEdgeBelow: 0.01,
    hysteresis: 1.25,
  },
  clearAfterMs: 1_000,
  smoothingFrames: 5,
  maxGapMs: 2_000,
};

/** The first threshold a signal crosses, and its level; null when it has none. */
export function firstThreshold(rule: SignalRule): { ms: number; level: Level } | null {
  const warn = rule.warn_after_ms;
  const critical = rule.critical_after_ms;
  if (warn !== undefined && (critical === undefined || warn <= critical)) {
    return { ms: warn, level: "warning" };
  }
  return critical === undefined ? null : { ms: critical, level: "critical" };
}

/** A transform of the config for one accommodation kind. */
export type Accommodation = (config: VisionConfig) => VisionConfig;

const double = (ms: number | undefined) => (ms === undefined ? undefined : ms * 2);

function scaled(rule: SignalRule): SignalRule {
  return withoutUndefined({
    warn_after_ms: double(rule.warn_after_ms),
    critical_after_ms: double(rule.critical_after_ms),
  });
}

/**
 * Accommodation kinds (interview-session.md's accommodation request) that change the camera's
 * rules. `relaxed_gaze` covers face distance too (master plan §6.4: "relaxed gaze/face-distance
 * rules"); nothing relaxes absence, multiple faces or obstruction. Kinds not listed here don't
 * concern the camera; SP-15b adds its gaze rules to this registry.
 */
export const ACCOMMODATIONS: Readonly<Record<string, Accommodation>> = {
  relaxed_gaze: (config) => ({
    ...config,
    signals: {
      ...config.signals,
      FACE_TOO_FAR: scaled(config.signals.FACE_TOO_FAR),
      FACE_TOO_CLOSE: scaled(config.signals.FACE_TOO_CLOSE),
    },
    face: { ...config.face, tooFarBelow: 0.1, tooCloseAbove: 0.75 },
  }),
};

/** Applies each known kind once, in the registry's order. */
export function applyAccommodations(config: VisionConfig, kinds: readonly string[]): VisionConfig {
  const wanted = new Set(kinds);
  let result = config;
  for (const [kind, accommodate] of Object.entries(ACCOMMODATIONS)) {
    if (wanted.has(kind)) result = accommodate(result);
  }
  return result;
}

/** The parts of `POST /proctoring/session`'s response the camera uses, as untrusted JSON. */
export interface VisionPolicy {
  thresholds?: Record<string, unknown>;
  accommodations?: readonly string[];
}

/**
 * The config for a proctor session: its `thresholds` override the defaults per signal and level
 * (null turns a level off; anything that isn't a non-negative number is ignored, as are signals
 * the camera doesn't raise), then its `accommodations` apply.
 */
export function visionConfigFromPolicy(
  policy: VisionPolicy,
  base: VisionConfig = DEFAULT_VISION_CONFIG,
): VisionConfig {
  const signals = { ...base.signals };
  for (const signal of CAMERA_SIGNALS) {
    const override = policy.thresholds?.[signal];
    if (typeof override === "object" && override !== null) {
      signals[signal] = mergeRule(signals[signal], override as Record<string, unknown>);
    }
  }
  return applyAccommodations({ ...base, signals }, policy.accommodations ?? []);
}

function mergeRule(rule: SignalRule, override: Record<string, unknown>): SignalRule {
  const merged: SignalRule = { ...rule };
  for (const key of ["warn_after_ms", "critical_after_ms"] as const) {
    const value = override[key];
    if (value === null) {
      delete merged[key];
    } else if (typeof value === "number" && Number.isFinite(value) && value >= 0) {
      merged[key] = value;
    }
  }
  return merged;
}

function withoutUndefined(rule: { [K in keyof SignalRule]: number | undefined }): SignalRule {
  const result: SignalRule = {};
  if (rule.warn_after_ms !== undefined) result.warn_after_ms = rule.warn_after_ms;
  if (rule.critical_after_ms !== undefined) result.critical_after_ms = rule.critical_after_ms;
  return result;
}
