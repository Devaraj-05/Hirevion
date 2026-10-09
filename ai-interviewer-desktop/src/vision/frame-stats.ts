import type { ObstructionRules } from "./config";
import type { FrameStats } from "./types";

/** Rec. 601 luma of an 8-bit RGB pixel, from 0 to 1. */
export function luma(r: number, g: number, b: number): number {
  return (0.299 * r + 0.587 * g + 0.114 * b) / 255;
}

/**
 * Mean and standard deviation of luma, and edge energy: the mean absolute luma difference
 * between horizontally and vertically neighbouring pixels. `rgba` is `ImageData.data` of a
 * small (e.g. 32x24) copy of the frame; alpha is ignored.
 */
export function frameStats(rgba: ArrayLike<number>, width: number, height: number): FrameStats {
  const count = width * height;
  if (rgba.length !== count * 4) {
    throw new RangeError(`expected ${count * 4} bytes for ${width}x${height}, got ${rgba.length}`);
  }
  if (count === 0) {
    return { meanLuma: 0, stdLuma: 0, edgeEnergy: 0 };
  }
  const lumas = new Float64Array(count);
  let sum = 0;
  for (let index = 0; index < count; index += 1) {
    const at = index * 4;
    const value = luma(rgba[at] ?? 0, rgba[at + 1] ?? 0, rgba[at + 2] ?? 0);
    lumas[index] = value;
    sum += value;
  }
  const mean = sum / count;
  let squares = 0;
  let edges = 0;
  let pairs = 0;
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const value = lumas[y * width + x] ?? 0;
      squares += (value - mean) ** 2;
      if (x + 1 < width) {
        edges += Math.abs((lumas[y * width + x + 1] ?? 0) - value);
        pairs += 1;
      }
      if (y + 1 < height) {
        edges += Math.abs((lumas[(y + 1) * width + x] ?? 0) - value);
        pairs += 1;
      }
    }
  }
  return {
    meanLuma: mean,
    stdLuma: Math.sqrt(squares / count),
    edgeEnergy: pairs === 0 ? 0 : edges / pairs,
  };
}

/**
 * A frame the camera can't see through: near black (a covered lens, a closed shutter) or flat,
 * with almost no spread or detail (a finger, tape or paper on the lens). Once obstructed
 * (`wasObstructed`), the bounds widen by `hysteresis` so a reading on the edge doesn't flap.
 * Callers only ask about frames with no face in them.
 */
export function isObstructedFrame(
  stats: FrameStats,
  rules: ObstructionRules,
  wasObstructed = false,
): boolean {
  const widen = wasObstructed ? rules.hysteresis : 1;
  const dark = stats.meanLuma < rules.darkBelow * widen;
  const flat =
    stats.stdLuma < rules.flatStdBelow * widen && stats.edgeEnergy < rules.flatEdgeBelow * widen;
  return dark || flat;
}
