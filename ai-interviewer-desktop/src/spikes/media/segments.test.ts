import { describe, expect, it } from "vitest";
import { SegmentClock } from "./segments";

const TEN_SECONDS_US = 10_000_000;
const ORIGIN = 5_000_000;

describe("SegmentClock", () => {
  it("makes the first timestamp time zero of segment 0", () => {
    const clock = new SegmentClock(TEN_SECONDS_US);
    expect(clock.place(ORIGIN)).toEqual({ segment: 0, offsetUs: 0 });
    expect(clock.place(ORIGIN + 9_999_999)).toEqual({ segment: 0, offsetUs: 9_999_999 });
  });

  it("starts a new segment every ten seconds", () => {
    const clock = new SegmentClock(TEN_SECONDS_US);
    clock.place(ORIGIN);
    expect(clock.place(ORIGIN + 10_000_000)).toEqual({ segment: 1, offsetUs: 0 });
    expect(clock.place(ORIGIN + 10_066_666)).toEqual({ segment: 1, offsetUs: 66_666 });
  });

  it("skips segments across a gap", () => {
    const clock = new SegmentClock(TEN_SECONDS_US);
    clock.place(ORIGIN);
    expect(clock.place(ORIGIN + 40_100_000)).toEqual({ segment: 4, offsetUs: 100_000 });
  });

  it("clamps timestamps from before the origin to the start", () => {
    const clock = new SegmentClock(TEN_SECONDS_US);
    clock.place(ORIGIN);
    expect(clock.place(ORIGIN - 1_000)).toEqual({ segment: 0, offsetUs: 0 });
  });
});
