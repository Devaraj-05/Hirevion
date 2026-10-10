import { describe, expect, it } from "vitest";
import { DEFAULT_VISION_CONFIG } from "./config";
import { frameStats, isObstructedFrame, luma } from "./frame-stats";

const OBSTRUCTION = DEFAULT_VISION_CONFIG.obstruction;

/** An RGBA frame whose every pixel comes from `pixel(x, y)` as [r, g, b]. */
function frame(
  width: number,
  height: number,
  pixel: (x: number, y: number) => readonly [number, number, number],
): Uint8ClampedArray {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const [r, g, b] = pixel(x, y);
      const at = (y * width + x) * 4;
      data[at] = r;
      data[at + 1] = g;
      data[at + 2] = b;
      data[at + 3] = 255;
    }
  }
  return data;
}

const grey = (value: number) => () => [value, value, value] as const;

describe("luma", () => {
  it("weighs the channels as Rec. 601 does, from 0 to 1", () => {
    expect(luma(0, 0, 0)).toBe(0);
    expect(luma(255, 255, 255)).toBeCloseTo(1, 6);
    expect(luma(0, 255, 0)).toBeCloseTo(0.587, 3);
    expect(luma(255, 0, 0)).toBeCloseTo(0.299, 3);
    expect(luma(0, 0, 255)).toBeCloseTo(0.114, 3);
  });
});

describe("frameStats", () => {
  it("measures a black frame as all zeros", () => {
    expect(frameStats(frame(32, 24, grey(0)), 32, 24)).toEqual({
      meanLuma: 0,
      stdLuma: 0,
      edgeEnergy: 0,
    });
  });

  it("measures a flat grey frame as mid luma with no spread or detail", () => {
    const stats = frameStats(frame(32, 24, grey(128)), 32, 24);
    expect(stats.meanLuma).toBeCloseTo(128 / 255, 6);
    expect(stats.stdLuma).toBeCloseTo(0, 6);
    expect(stats.edgeEnergy).toBeCloseTo(0, 6);
  });

  it("measures a black-and-white checkerboard as half luma, full spread and full detail", () => {
    const board = frame(32, 24, (x, y) => ((x + y) % 2 === 0 ? [0, 0, 0] : [255, 255, 255]));
    const stats = frameStats(board, 32, 24);
    expect(stats.meanLuma).toBeCloseTo(0.5, 6);
    expect(stats.stdLuma).toBeCloseTo(0.5, 6);
    expect(stats.edgeEnergy).toBeCloseTo(1, 6);
  });

  it("measures a vertical gradient's detail from neighbouring rows", () => {
    // Rows step by 10 levels: horizontal neighbours are equal, vertical ones differ by 10.
    const gradient = frame(4, 3, (_x, y) => [y * 10, y * 10, y * 10]);
    const stats = frameStats(gradient, 4, 3);
    expect(stats.meanLuma).toBeCloseTo(10 / 255, 6);
    // 9 horizontal pairs at 0 and 8 vertical pairs at 10/255.
    expect(stats.edgeEnergy).toBeCloseTo((8 * (10 / 255)) / 17, 6);
  });

  it("ignores the alpha channel", () => {
    const opaque = frame(8, 8, grey(90));
    const clear = new Uint8ClampedArray(opaque);
    for (let at = 3; at < clear.length; at += 4) clear[at] = 0;
    expect(frameStats(clear, 8, 8)).toEqual(frameStats(opaque, 8, 8));
  });

  it("measures an empty frame as zeros", () => {
    expect(frameStats(new Uint8ClampedArray(0), 0, 0)).toEqual({
      meanLuma: 0,
      stdLuma: 0,
      edgeEnergy: 0,
    });
  });

  it("refuses pixel data that doesn't match the size", () => {
    expect(() => frameStats(new Uint8ClampedArray(10), 4, 4)).toThrow(RangeError);
  });
});

describe("isObstructedFrame", () => {
  const stats = (pixel: (x: number, y: number) => readonly [number, number, number]) =>
    frameStats(frame(32, 24, pixel), 32, 24);

  it("calls a covered lens (near black) obstructed", () => {
    expect(isObstructedFrame(stats(grey(4)), OBSTRUCTION)).toBe(true);
  });

  it("calls a flat surface in front of the lens obstructed, even when bright", () => {
    expect(isObstructedFrame(stats(grey(200)), OBSTRUCTION)).toBe(true);
  });

  it("calls a flat frame with sensor noise obstructed", () => {
    const noisy = stats((x, y) => {
      const value = 120 + ((x * 7 + y * 13) % 3);
      return [value, value, value];
    });
    expect(isObstructedFrame(noisy, OBSTRUCTION)).toBe(true);
  });

  it("doesn't call a dim room with detail obstructed", () => {
    const dim = stats((x, y) => {
      const value = 20 + ((x * 7 + y * 13) % 50);
      return [value, value, value];
    });
    expect(dim.meanLuma).toBeLessThan(0.25);
    expect(isObstructedFrame(dim, OBSTRUCTION)).toBe(false);
  });

  it("doesn't call a normal scene obstructed", () => {
    const scene = stats((x, y) => [(x * 8) % 256, (y * 10) % 256, ((x + y) * 6) % 256]);
    expect(isObstructedFrame(scene, OBSTRUCTION)).toBe(false);
  });

  it("stays obstructed a little above the threshold once obstructed (hysteresis)", () => {
    const justAbove = { meanLuma: 0.07, stdLuma: 0.2, edgeEnergy: 0.2 };
    expect(isObstructedFrame(justAbove, OBSTRUCTION, false)).toBe(false);
    expect(isObstructedFrame(justAbove, OBSTRUCTION, true)).toBe(true);
    const wellAbove = { meanLuma: 0.2, stdLuma: 0.2, edgeEnergy: 0.2 };
    expect(isObstructedFrame(wellAbove, OBSTRUCTION, true)).toBe(false);
  });
});
