/**
 * The face module's frame rate, kept inside a CPU budget (master plan: 5–10 fps; SP-15a exit
 * criterion "CPU stays within budget while recording"). The worker's time per frame (detection
 * plus luminance) times the frame rate is the share of a core it keeps busy.
 */
export interface FrameRateConfig {
  minFps: number;
  maxFps: number;
  initialFps: number;
  /** Worker time allowed per second: 150 ms is 15 % of one core. */
  budgetMsPerSecond: number;
  /** Climb only when the next rate would use at most this share of the budget. */
  upHeadroom: number;
  /** At most one climb per this long, and none this soon after a change. */
  upAfterMs: number;
  /** Recent frames whose median is judged, and how many are needed before judging. */
  window: number;
  minSamples: number;
}

/**
 * ADR-0007 measured 9.9 ms (GPU) and 13.0 ms (CPU) per frame at p50 on the development PC, so
 * 10 fps uses 100–130 ms per second there; a PC twice as slow drops to 5 fps.
 */
export const DEFAULT_FRAME_RATE: FrameRateConfig = {
  minFps: 5,
  maxFps: 10,
  initialFps: 10,
  budgetMsPerSecond: 150,
  upHeadroom: 0.7,
  upAfterMs: 5_000,
  window: 10,
  minSamples: 3,
};

export interface FrameRateState {
  fps: number;
  /** The latest frame times, oldest first. */
  samples: readonly number[];
  /** Their median; null before the first frame. */
  medianMs: number | null;
  /** When the rate last changed; null before any change. */
  changedAt: number | null;
  /** True when even the lowest rate doesn't fit the budget. */
  overBudget: boolean;
}

export function initialFrameRate(config: FrameRateConfig = DEFAULT_FRAME_RATE): FrameRateState {
  return {
    fps: config.initialFps,
    samples: [],
    medianMs: null,
    changedAt: null,
    overBudget: false,
  };
}

/**
 * Adds one frame's worker time. Over budget, the rate drops at once to the fastest one that
 * fits (a median, so one slow frame doesn't count); with headroom it climbs 1 fps at a time.
 */
export function nextFrameRate(
  state: FrameRateState,
  frameMs: number,
  now: number,
  config: FrameRateConfig = DEFAULT_FRAME_RATE,
): FrameRateState {
  const samples = [...state.samples, Math.max(0, frameMs)].slice(-config.window);
  const medianMs = median(samples);
  const next: FrameRateState = { ...state, samples, medianMs };
  if (samples.length < config.minSamples) {
    return next;
  }
  const fitting = medianMs === 0 ? config.maxFps : Math.floor(config.budgetMsPerSecond / medianMs);
  next.overBudget = medianMs * config.minFps > config.budgetMsPerSecond;
  if (fitting < state.fps && state.fps > config.minFps) {
    return { ...next, fps: Math.max(config.minFps, fitting), changedAt: now };
  }
  const settled = state.changedAt === null || now - state.changedAt >= config.upAfterMs;
  const roomy = medianMs * (state.fps + 1) <= config.budgetMsPerSecond * config.upHeadroom;
  if (state.fps < config.maxFps && settled && roomy) {
    return { ...next, fps: state.fps + 1, changedAt: now };
  }
  return next;
}

function median(values: readonly number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  if (sorted.length % 2 === 1) return sorted[middle] ?? 0;
  return ((sorted[middle - 1] ?? 0) + (sorted[middle] ?? 0)) / 2;
}
