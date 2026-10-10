import { classifyFrame, type FrameReading } from "./classify";
import { firstThreshold, type VisionConfig } from "./config";
import {
  CAMERA_SIGNALS,
  type CameraEvent,
  type CameraSignal,
  type EpisodeDetails,
  type FaceObservation,
  type Level,
  type Phase,
} from "./types";

/**
 * The temporal rule engine: a pure reducer from frames to §56's episodes. Each signal is an
 * episode tracker, idle → pending → active → idle:
 *
 * - a majority filter over the last `smoothingFrames` frames decides whether the condition
 *   holds, so a sparse detector mistake neither starts nor sustains an episode;
 * - an episode starts at its first frame with the condition, and holding past the first
 *   threshold (strictly) makes it active and raises `started`; past critical, `escalated`;
 * - the condition gone for `clearAfterMs` ends it, raising `ended` with the duration up to the
 *   first frame without it, so a short gap never splits an episode;
 * - no frame for `maxGapMs` ends open episodes at their last frame.
 */

/** One episode transition, in monotonic milliseconds. */
export interface SignalEvent {
  signal: CameraSignal;
  phase: Phase;
  level: Level;
  startedAtMs: number;
  durationMs: number;
  /** Share of the episode's frames where the condition held × their mean confidence. */
  confidence: number;
  details: EpisodeDetails;
}

/** One frame's reading for one signal, kept for the majority filter. */
interface Sample {
  t: number;
  on: boolean;
  confidence: number;
  faces: number;
  faceHeight: number | null;
  meanLuma: number | null;
}

interface Tracker {
  status: "idle" | "pending" | "active";
  /** The latest frames, oldest first. */
  window: readonly Sample[];
  start: number;
  /** The episode's latest frame with the condition. */
  lastOn: number;
  /** While the filtered condition is off: the first frame without it after `lastOn`. */
  offSince: number | null;
  level: Level | null;
  /** Frames since the episode started, and that count at its latest frame with the condition. */
  frames: number;
  framesAtLastOn: number;
  onFrames: number;
  confidenceSum: number;
  maxFaces: number;
  heightSum: number;
  heightFrames: number;
  lumaSum: number;
  lumaFrames: number;
}

export interface EngineState {
  /** The last frame's time; null before the first. */
  t: number | null;
  trackers: Readonly<Record<CameraSignal, Tracker>>;
}

export interface EngineStep {
  state: EngineState;
  events: SignalEvent[];
}

const EMPTY_EPISODE = {
  status: "idle",
  start: 0,
  lastOn: 0,
  offSince: null,
  level: null,
  frames: 0,
  framesAtLastOn: 0,
  onFrames: 0,
  confidenceSum: 0,
  maxFaces: 0,
  heightSum: 0,
  heightFrames: 0,
  lumaSum: 0,
  lumaFrames: 0,
} as const satisfies Omit<Tracker, "window">;

function allIdle(): Record<CameraSignal, Tracker> {
  const idle: Tracker = { ...EMPTY_EPISODE, window: [] };
  return {
    FACE_ABSENT: idle,
    MULTIPLE_FACES: idle,
    FACE_TOO_FAR: idle,
    FACE_TOO_CLOSE: idle,
    CAMERA_OBSTRUCTED: idle,
  };
}

export function initialEngineState(): EngineState {
  return { t: null, trackers: allIdle() };
}

/** Feeds one frame. A frame no newer than the last one is ignored. */
export function stepEngine(
  state: EngineState,
  observation: FaceObservation,
  config: VisionConfig,
): EngineStep {
  if (state.t !== null && observation.t <= state.t) {
    return { state, events: [] };
  }
  const events: SignalEvent[] = [];
  let trackers = { ...state.trackers };
  if (state.t !== null && observation.t - state.t > config.maxGapMs) {
    const flushed = flushEngine({ t: state.t, trackers });
    trackers = { ...flushed.state.trackers };
    events.push(...flushed.events);
  }
  const wasOn = {} as Record<CameraSignal, boolean>;
  for (const signal of CAMERA_SIGNALS) {
    wasOn[signal] = trackers[signal].window.at(-1)?.on ?? false;
  }
  const reading = classifyFrame(observation, config, wasOn);
  for (const signal of CAMERA_SIGNALS) {
    const sample = sampleOf(reading, signal, observation.t);
    const next = stepTracker(trackers[signal], signal, sample, config);
    trackers[signal] = next.tracker;
    events.push(...next.events);
  }
  return { state: { t: observation.t, trackers }, events };
}

/**
 * Ends every open episode at its last frame with the condition (or the first frame without it),
 * as when the module stops or frames stop arriving. Pending episodes end silently, and the
 * majority filter starts afresh.
 */
export function flushEngine(state: EngineState): EngineStep {
  const events: SignalEvent[] = [];
  for (const signal of CAMERA_SIGNALS) {
    const tracker = state.trackers[signal];
    if (tracker.status === "active") {
      const end = tracker.offSince ?? tracker.lastOn;
      events.push(episodeEvent(tracker, signal, "ended", end - tracker.start));
    }
  }
  return { state: { t: state.t, trackers: allIdle() }, events };
}

/** The signals with an active (reported) episode. */
export function activeSignals(state: EngineState): CameraSignal[] {
  return CAMERA_SIGNALS.filter((signal) => state.trackers[signal].status === "active");
}

function sampleOf(reading: FrameReading, signal: CameraSignal, t: number): Sample {
  const { on, confidence } = reading.signals[signal];
  return {
    t,
    on,
    confidence,
    faces: reading.faces,
    faceHeight: reading.faceHeight,
    meanLuma: reading.meanLuma,
  };
}

function stepTracker(
  tracker: Tracker,
  signal: CameraSignal,
  sample: Sample,
  config: VisionConfig,
): { tracker: Tracker; events: SignalEvent[] } {
  const window = [...tracker.window, sample].slice(-Math.max(1, config.smoothingFrames));
  const held = 2 * window.filter((entry) => entry.on).length > window.length;
  const events: SignalEvent[] = [];
  let next: Tracker;
  if (tracker.status === "idle") {
    if (!held) return { tracker: { ...tracker, window }, events };
    // The filter turns on only on a frame with the condition; the episode began at the
    // window's first such frame.
    const firstOn = window.findIndex((entry) => entry.on);
    next = { ...EMPTY_EPISODE, window, status: "pending", start: window[firstOn]?.t ?? sample.t };
    for (const entry of window.slice(firstOn)) next = count(next, entry);
  } else {
    next = count({ ...tracker, window }, sample);
  }

  if (held) {
    next = { ...next, offSince: null };
    if (sample.on) {
      const elapsed = sample.t - next.start;
      const rule = config.signals[signal];
      const first = firstThreshold(rule);
      if (next.status === "pending" && first && elapsed > first.ms) {
        next = { ...next, status: "active", level: first.level };
        events.push(episodeEvent(next, signal, "started", elapsed));
      }
      const critical = rule.critical_after_ms;
      if (
        next.status === "active" &&
        next.level === "warning" &&
        critical !== undefined &&
        elapsed > critical
      ) {
        next = { ...next, level: "critical" };
        events.push(episodeEvent(next, signal, "escalated", elapsed));
      }
    }
    return { tracker: next, events };
  }

  const lastOn = next.lastOn;
  const offSince = next.offSince ?? window.find((entry) => entry.t > lastOn)?.t ?? sample.t;
  next = { ...next, offSince };
  if (sample.t - offSince >= config.clearAfterMs) {
    if (next.status === "active") {
      events.push(episodeEvent(next, signal, "ended", offSince - next.start));
    }
    next = { ...EMPTY_EPISODE, window };
  }
  return { tracker: next, events };
}

/** Adds one frame to an episode's counts. */
function count(tracker: Tracker, sample: Sample): Tracker {
  const frames = tracker.frames + 1;
  if (!sample.on) return { ...tracker, frames };
  const next = {
    ...tracker,
    frames,
    framesAtLastOn: frames,
    lastOn: sample.t,
    onFrames: tracker.onFrames + 1,
    confidenceSum: tracker.confidenceSum + sample.confidence,
    maxFaces: Math.max(tracker.maxFaces, sample.faces),
  };
  if (sample.faceHeight !== null) {
    next.heightSum += sample.faceHeight;
    next.heightFrames += 1;
  }
  if (sample.meanLuma !== null) {
    next.lumaSum += sample.meanLuma;
    next.lumaFrames += 1;
  }
  return next;
}

function episodeEvent(
  tracker: Tracker,
  signal: CameraSignal,
  phase: Phase,
  durationMs: number,
): SignalEvent {
  const frames = tracker.framesAtLastOn;
  const onRatio = frames === 0 ? 0 : tracker.onFrames / frames;
  const meanConfidence = tracker.onFrames === 0 ? 0 : tracker.confidenceSum / tracker.onFrames;
  const details: EpisodeDetails = { frames };
  if (signal === "MULTIPLE_FACES") {
    details.max_faces = tracker.maxFaces;
  } else if ((signal === "FACE_TOO_FAR" || signal === "FACE_TOO_CLOSE") && tracker.heightFrames) {
    details.face_height = tracker.heightSum / tracker.heightFrames;
  } else if (signal === "CAMERA_OBSTRUCTED" && tracker.lumaFrames > 0) {
    details.mean_luma = tracker.lumaSum / tracker.lumaFrames;
  }
  return {
    signal,
    phase,
    level: tracker.level ?? "warning",
    startedAtMs: tracker.start,
    durationMs,
    confidence: onRatio * meanConfidence,
    details,
  };
}

/** Converts a monotonic time to an ISO timestamp. */
export type ServerClock = (monotonicMs: number) => string;

/**
 * The wall clock: SP-08b passes a server-time clock instead (interview-session.md's clock
 * sync), since `started_at` is in server time.
 */
export const localClock: ServerClock = (monotonicMs) =>
  new Date(performance.timeOrigin + monotonicMs).toISOString();

const round = (value: number, places: number) => {
  const factor = 10 ** places;
  return Math.round(value * factor) / factor;
};

/** The `proctoring.md` event for an episode transition, without `seq` (the native queue adds it). */
export function toCameraEvent(event: SignalEvent, toServerIso: ServerClock): CameraEvent {
  return {
    event: event.signal,
    source: "camera",
    started_at: toServerIso(event.startedAtMs),
    duration_ms: Math.round(event.durationMs),
    confidence: round(event.confidence, 2),
    evidence: [],
    details: { phase: event.phase, level: event.level, ...event.details },
  };
}

export interface SignalEngineOptions {
  onEvent?: (event: CameraEvent) => void;
  toServerIso?: ServerClock;
}

/** The reducer with its state, emitting contract events through a callback. */
export class SignalEngine {
  private state = initialEngineState();
  private readonly onEvent: (event: CameraEvent) => void;
  private readonly toServerIso: ServerClock;

  constructor(
    private readonly config: VisionConfig,
    options: SignalEngineOptions = {},
  ) {
    this.onEvent = options.onEvent ?? (() => {});
    this.toServerIso = options.toServerIso ?? localClock;
  }

  /** Feeds one frame; returns the events it raised (also sent to `onEvent`). */
  push(observation: FaceObservation): CameraEvent[] {
    const step = stepEngine(this.state, observation, this.config);
    this.state = step.state;
    return this.emit(step.events);
  }

  /** Ends every open episode (on stop, pause or a break). */
  flush(): CameraEvent[] {
    const step = flushEngine(this.state);
    this.state = step.state;
    return this.emit(step.events);
  }

  /** The signals currently reported, e.g. to nudge the candidate. */
  active(): CameraSignal[] {
    return activeSignals(this.state);
  }

  private emit(events: readonly SignalEvent[]): CameraEvent[] {
    const built = events.map((event) => toCameraEvent(event, this.toServerIso));
    for (const event of built) this.onEvent(event);
    return built;
  }
}
