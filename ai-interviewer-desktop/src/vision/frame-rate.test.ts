import { describe, expect, it } from "vitest";
import {
  DEFAULT_FRAME_RATE,
  type FrameRateState,
  initialFrameRate,
  nextFrameRate,
} from "./frame-rate";

/** Feeds `count` frames of `ms` each at the current rate, from `start`; returns the state and time. */
function feed(state: FrameRateState, ms: number, count: number, start = 0) {
  let t = start;
  let current = state;
  for (let index = 0; index < count; index += 1) {
    t += 1_000 / current.fps;
    current = nextFrameRate(current, ms, t);
  }
  return { state: current, t };
}

describe("the adaptive frame rate", () => {
  it("starts at 10 fps, within the master plan's 5–10 fps", () => {
    expect(DEFAULT_FRAME_RATE.minFps).toBe(5);
    expect(DEFAULT_FRAME_RATE.maxFps).toBe(10);
    expect(initialFrameRate().fps).toBe(10);
  });

  it("stays at 10 fps at ADR-0007's measured GPU inference time", () => {
    const { state } = feed(initialFrameRate(), 10, 200);
    expect(state.fps).toBe(10);
    expect(state.overBudget).toBe(false);
  });

  it("drops to the fastest rate that fits the budget when inference is slow", () => {
    expect(feed(initialFrameRate(), 20, 30).state.fps).toBe(7);
    expect(feed(initialFrameRate(), 30, 30).state.fps).toBe(5);
  });

  it("never goes below 5 fps, and says when even that is over budget", () => {
    const { state } = feed(initialFrameRate(), 60, 30);
    expect(state.fps).toBe(5);
    expect(state.overBudget).toBe(true);
  });

  it("ignores a single slow frame", () => {
    let { state, t } = feed(initialFrameRate(), 10, 20);
    state = nextFrameRate(state, 120, t + 100);
    ({ state } = feed(state, 10, 5, t + 100));
    expect(state.fps).toBe(10);
  });

  it("waits for a few frames before judging", () => {
    let state = initialFrameRate();
    state = nextFrameRate(state, 80, 100);
    state = nextFrameRate(state, 80, 200);
    expect(state.fps).toBe(10);
    state = nextFrameRate(state, 80, 300);
    expect(state.fps).toBe(5);
  });

  it("climbs back 1 fps at a time, at most every 5 s, when there is headroom", () => {
    let state = initialFrameRate();
    let t = 0;
    const changes: Array<[number, number]> = [];
    const run = (ms: number, frames: number) => {
      for (let index = 0; index < frames; index += 1) {
        t += 1_000 / state.fps;
        const next = nextFrameRate(state, ms, t);
        if (next.fps !== state.fps) changes.push([t, next.fps]);
        state = next;
      }
    };
    run(30, 30);
    run(8, 300);
    const [drop, ...climbs] = changes;
    expect(drop?.[1]).toBe(5);
    expect(climbs.map(([, fps]) => fps)).toEqual([6, 7, 8, 9, 10]);
    let previous = drop?.[0] ?? 0;
    for (const [at] of climbs) {
      expect(at - previous).toBeGreaterThanOrEqual(5_000);
      previous = at;
    }
  });

  it("doesn't climb into a rate that would use most of the budget", () => {
    // 15 ms × 8 fps = 120 ms/s, over 70 % of the 150 ms budget, so 7 fps holds.
    let { state, t } = feed(initialFrameRate(), 20, 30);
    expect(state.fps).toBe(7);
    ({ state, t } = feed(state, 15, 200, t));
    expect(state.fps).toBe(7);
  });

  it("measures the median of recent frames", () => {
    const { state } = feed(initialFrameRate(), 12, 15);
    expect(state.medianMs).toBe(12);
  });
});
