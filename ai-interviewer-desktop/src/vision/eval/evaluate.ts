import { DEFAULT_VISION_CONFIG, firstThreshold, type VisionConfig } from "../config";
import { flushEngine, initialEngineState, type SignalEvent, stepEngine } from "../engine";
import { CAMERA_SIGNALS, type CameraSignal, type FaceObservation, type FrameStats } from "../types";

/**
 * The SP-15a exit criterion's harness: precision and recall per signal over labelled
 * timelines. A timeline is the face module's observations for a clip plus the intervals a
 * person marked where each condition held; the engine's reported episodes are matched to them.
 */

/** A labeller's interval: the condition held from `start_ms` to `end_ms` of the clip. */
export interface LabelInterval {
  signal: CameraSignal;
  start_ms: number;
  end_ms: number;
}

export interface LabelledTimeline {
  clip: string;
  observations: FaceObservation[];
  labels: LabelInterval[];
}

export interface Span {
  start: number;
  end: number;
}

export interface IntervalScore {
  tp: number;
  fp: number;
  fn: number;
  /** Reported episodes over labels within the tolerance of the threshold: not counted. */
  ignored: number;
}

export interface SignalScore extends IntervalScore {
  /** 1 when nothing was reported. */
  precision: number;
  /** 1 when nothing reportable was labelled. */
  recall: number;
}

export interface EvaluationReport {
  clips: number;
  signals: Record<CameraSignal, SignalScore>;
}

export interface Target {
  precision: number;
  recall: number;
}

/** Proposed for CP2 (SP-15a plan): the exit criterion names absent and multiple faces. */
export const EXIT_TARGETS: Partial<Record<CameraSignal, Target>> = {
  FACE_ABSENT: { precision: 0.9, recall: 0.9 },
  MULTIPLE_FACES: { precision: 0.9, recall: 0.9 },
};

/** A label this close to the threshold (either side) may fairly be reported or not. */
export const DEFAULT_TOLERANCE_MS = 500;

const overlaps = (a: Span, b: Span) => a.start < b.end && b.start < a.end;

/**
 * Scores reported episodes against labels of one signal. Labels longer than the threshold plus
 * the tolerance must be reported; those within the tolerance are "don't care"; shorter ones must
 * not be. Each label matches at most one episode, in time order.
 */
export function scoreIntervals(
  predicted: readonly Span[],
  labels: readonly Span[],
  thresholdMs: number,
  toleranceMs: number = DEFAULT_TOLERANCE_MS,
): IntervalScore {
  const duration = (span: Span) => span.end - span.start;
  const byStart = (a: Span, b: Span) => a.start - b.start;
  const reportable = labels.filter((l) => duration(l) > thresholdMs + toleranceMs).sort(byStart);
  const unsure = labels.filter(
    (l) => duration(l) > thresholdMs - toleranceMs && duration(l) <= thresholdMs + toleranceMs,
  );
  const unmatched = [...predicted].sort(byStart);
  let tp = 0;
  let fn = 0;
  for (const label of reportable) {
    const index = unmatched.findIndex((episode) => overlaps(episode, label));
    if (index === -1) {
      fn += 1;
    } else {
      tp += 1;
      unmatched.splice(index, 1);
    }
  }
  const ignored = unmatched.filter((episode) => unsure.some((l) => overlaps(episode, l))).length;
  return { tp, fp: unmatched.length - ignored, fn, ignored };
}

/** Runs the engine over a clip and returns each reported episode's span, the last one closed. */
export function predictedEpisodes(
  observations: readonly FaceObservation[],
  config: VisionConfig,
): Array<{ signal: CameraSignal } & Span> {
  let state = initialEngineState();
  const ended: SignalEvent[] = [];
  const keep = (events: readonly SignalEvent[]) => {
    for (const event of events) if (event.phase === "ended") ended.push(event);
  };
  for (const observation of observations) {
    const step = stepEngine(state, observation, config);
    state = step.state;
    keep(step.events);
  }
  keep(flushEngine(state).events);
  return ended.map((event) => ({
    signal: event.signal,
    start: event.startedAtMs,
    end: event.startedAtMs + event.durationMs,
  }));
}

const ratio = (part: number, whole: number) => (whole === 0 ? 1 : part / whole);

/** Precision and recall per signal over every clip. Signals without a threshold score empty. */
export function evaluate(
  timelines: readonly LabelledTimeline[],
  config: VisionConfig = DEFAULT_VISION_CONFIG,
  toleranceMs: number = DEFAULT_TOLERANCE_MS,
): EvaluationReport {
  const totals = Object.fromEntries(
    CAMERA_SIGNALS.map((signal) => [signal, { tp: 0, fp: 0, fn: 0, ignored: 0 }]),
  ) as Record<CameraSignal, IntervalScore>;
  for (const timeline of timelines) {
    const episodes = predictedEpisodes(timeline.observations, config);
    for (const signal of CAMERA_SIGNALS) {
      const threshold = firstThreshold(config.signals[signal]);
      if (!threshold) continue;
      const score = scoreIntervals(
        episodes.filter((episode) => episode.signal === signal),
        timeline.labels
          .filter((label) => label.signal === signal)
          .map((label) => ({ start: label.start_ms, end: label.end_ms })),
        threshold.ms,
        toleranceMs,
      );
      const total = totals[signal];
      total.tp += score.tp;
      total.fp += score.fp;
      total.fn += score.fn;
      total.ignored += score.ignored;
    }
  }
  const signals = Object.fromEntries(
    CAMERA_SIGNALS.map((signal) => {
      const { tp, fp, fn, ignored } = totals[signal];
      return [
        signal,
        { tp, fp, fn, ignored, precision: ratio(tp, tp + fp), recall: ratio(tp, tp + fn) },
      ];
    }),
  ) as Record<CameraSignal, SignalScore>;
  return { clips: timelines.length, signals };
}

/** Whether every targeted signal meets its precision and recall, naming the ones that don't. */
export function meetsTargets(
  report: EvaluationReport,
  targets: Partial<Record<CameraSignal, Target>>,
): { ok: boolean; failures: string[] } {
  const failures: string[] = [];
  for (const signal of CAMERA_SIGNALS) {
    const target = targets[signal];
    if (!target) continue;
    const score = report.signals[signal];
    for (const measure of ["precision", "recall"] as const) {
      if (score[measure] < target[measure]) {
        failures.push(
          `${signal} ${measure} ${score[measure].toFixed(2)} < ${target[measure].toFixed(2)}`,
        );
      }
    }
  }
  return { ok: failures.length === 0, failures };
}

/**
 * Reads a labelled clip file: `{ version: 1, clip, observations, labels }`, as written by
 * recording `startFaceModule`'s `onObservation` over a clip and adding a person's labels.
 */
export function parseLabelledTimeline(json: unknown): LabelledTimeline {
  const file = record(json, "clip file");
  if (file.version !== 1) throw new Error("unsupported clip file version");
  if (typeof file.clip !== "string") throw new Error("clip name missing");
  if (!Array.isArray(file.observations) || !Array.isArray(file.labels)) {
    throw new Error("observations and labels must be arrays");
  }
  return {
    clip: file.clip,
    observations: file.observations.map(parseObservation),
    labels: file.labels.map(parseLabel),
  };
}

function record(value: unknown, what: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${what} must be an object`);
  }
  return value as Record<string, unknown>;
}

const isNumber = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);

function numbers<K extends string>(value: unknown, keys: readonly K[], what: string) {
  const object = record(value, what);
  const result = {} as Record<K, number>;
  for (const key of keys) {
    const field = object[key];
    if (!isNumber(field)) throw new Error(`${what}: ${key} must be a number`);
    result[key] = field;
  }
  return result;
}

function parseObservation(value: unknown): FaceObservation {
  const object = record(value, "observation");
  if (!isNumber(object.t) || !Array.isArray(object.faces)) {
    throw new Error("observation: t and faces are required");
  }
  const frame: FrameStats | null =
    object.frame === null || object.frame === undefined
      ? null
      : numbers(object.frame, ["meanLuma", "stdLuma", "edgeEnergy"], "frame");
  return {
    t: object.t,
    faces: object.faces.map((face) =>
      numbers(face, ["x", "y", "width", "height", "score"], "face"),
    ),
    frame,
  };
}

function parseLabel(value: unknown): LabelInterval {
  const object = record(value, "label");
  const signal = object.signal;
  if (typeof signal !== "string" || !(CAMERA_SIGNALS as readonly string[]).includes(signal)) {
    throw new Error(`label: unknown signal ${String(signal)}`);
  }
  const { start_ms, end_ms } = numbers(value, ["start_ms", "end_ms"], "label");
  if (end_ms < start_ms) throw new Error("label ends before it starts");
  return { signal: signal as CameraSignal, start_ms, end_ms };
}
