import { describe, expect, it } from "vitest";
import { follow, level, scales, voiced } from "./levels";

describe("sound levels for the orb (C8-12)", () => {
  it("is zero for silence and grows with loudness, capped at one", () => {
    expect(level(new Uint8Array(64).fill(128))).toBe(0);
    const quiet = Uint8Array.from({ length: 64 }, (_, n) => (n % 2 ? 136 : 120));
    const loud = Uint8Array.from({ length: 64 }, (_, n) => (n % 2 ? 200 : 56));
    expect(level(quiet)).toBeGreaterThan(0);
    expect(level(loud)).toBeGreaterThan(level(quiet));
    expect(level(Uint8Array.from({ length: 64 }, (_, n) => (n % 2 ? 255 : 0)))).toBe(1);
  });

  it("follows the target smoothly, without overshoot", () => {
    let value = 0;
    const seen: number[] = [];
    for (let frame = 0; frame < 30; frame += 1) {
      value = follow(value, 1, 16);
      seen.push(value);
    }
    expect(seen.every((one, n) => one > (seen[n - 1] ?? 0) && one <= 1)).toBe(true);
    expect(value).toBeGreaterThan(0.95);
    expect(follow(0.5, 0.5, 16)).toBe(0.5);
  });

  it("counts speech only above a threshold, with hysteresis so it doesn't flicker", () => {
    expect(voiced(0.02, false)).toBe(false);
    expect(voiced(0.2, false)).toBe(true);
    expect(voiced(0.08, true)).toBe(true);
    expect(voiced(0.08, false)).toBe(false);
    expect(voiced(0.02, true)).toBe(false);
  });
});

describe("what the level moves (perf, 2026-11-24)", () => {
  it("scales the sphere, the three rings and the waveform, resting at silence", () => {
    expect(scales(0)).toEqual({ core: 1, rings: [1, 1, 1], strip: 0.6 });
    expect(scales(1)).toEqual({ core: 1.04, rings: [1.05, 1.09, 1.14], strip: 1 });
    const half = scales(0.5);
    expect(half.core).toBeCloseTo(1.02);
    expect(half.strip).toBeCloseTo(0.8);
  });
});
