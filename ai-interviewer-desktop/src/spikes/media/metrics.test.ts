import { describe, expect, it } from "vitest";
import { FpsMeter, summarize } from "./metrics";

describe("FpsMeter", () => {
  it("reports the rate of ticks in the last second", () => {
    const meter = new FpsMeter(1_000);
    for (let tick = 0; tick < 45; tick += 1) {
      meter.tick((tick * 1_000) / 15);
    }
    expect(meter.fps(3_000)).toBeCloseTo(15, 0);
  });

  it("drops to zero when ticks stop", () => {
    const meter = new FpsMeter(1_000);
    meter.tick(0);
    meter.tick(100);
    expect(meter.fps(2_500)).toBe(0);
  });

  it("is zero before any tick", () => {
    expect(new FpsMeter(1_000).fps(0)).toBe(0);
  });
});

describe("summarize", () => {
  it("returns p50, p95 and max with linear interpolation", () => {
    const values = Array.from({ length: 100 }, (_, index) => index + 1);
    const summary = summarize(values);
    expect(summary).toMatchObject({ count: 100, max: 100 });
    expect(summary?.p50).toBeCloseTo(50.5);
    expect(summary?.p95).toBeCloseTo(95.05);
  });

  it("returns null for no values", () => {
    expect(summarize([])).toBeNull();
  });
});
