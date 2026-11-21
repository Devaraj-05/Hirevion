import { describe, expect, it } from "vitest";
import {
  answerBars,
  niceCeiling,
  splitDuration,
  timelinePercent,
  withAnswers,
} from "./analytics-model";

describe("niceCeiling", () => {
  it("rounds an axis maximum up to 1, 2 or 5 of a power of ten", () => {
    expect(niceCeiling(0)).toBe(1);
    expect(niceCeiling(0.7)).toBe(1);
    expect(niceCeiling(7)).toBe(10);
    expect(niceCeiling(13)).toBe(20);
    expect(niceCeiling(41)).toBe(50);
    expect(niceCeiling(64_000)).toBe(100_000);
  });
});

describe("timelinePercent", () => {
  it("places an event along the interview, inside the strip", () => {
    expect(timelinePercent(30_000, 60_000)).toBe(50);
    expect(timelinePercent(90_000, 60_000)).toBe(100);
    expect(timelinePercent(-5, 60_000)).toBe(0);
  });

  it("has no place without a time or a length", () => {
    expect(timelinePercent(null, 60_000)).toBeNull();
    expect(timelinePercent(1_000, null)).toBeNull();
    expect(timelinePercent(1_000, 0)).toBeNull();
  });
});

describe("answerBars", () => {
  it("draws thinking and speaking time on one scale, rounded up to clean seconds", () => {
    const bars = answerBars([
      { position: 1, thinking_ms: 3_000, speaking_ms: 7_000 },
      { position: 2, thinking_ms: null, speaking_ms: 0 },
      { position: 3, thinking_ms: 12_000, speaking_ms: 4_000 },
    ]);
    expect(bars.max).toBe(20_000);
    expect(bars.rows[0]).toMatchObject({ position: 1, thinking: 15, speaking: 35 });
    expect(bars.rows[1]).toMatchObject({ position: 2, thinking: 0, speaking: 0 });
    expect(bars.rows[2]).toMatchObject({ thinking: 60, speaking: 20 });
  });
});

describe("withAnswers", () => {
  it("keeps the questions put to the candidate, not the closing one nobody answered", () => {
    const kept = withAnswers([
      { kind: "introduction", status: "answered" },
      { kind: "main", status: "answered" },
      { kind: "main", status: "skipped" },
      { kind: "final", status: "asked" },
    ]);
    expect(kept.map((q) => q.kind)).toEqual(["introduction", "main"]);
  });
});

describe("splitDuration", () => {
  it("gives whole minutes and seconds", () => {
    expect(splitDuration(760_199)).toEqual({ minutes: 12, seconds: 40 });
    expect(splitDuration(59_600)).toEqual({ minutes: 1, seconds: 0 });
    expect(splitDuration(null)).toBeNull();
  });
});
