import { describe, expect, it } from "vitest";
import {
  DEFAULT_GAZE_RULES,
  GazeBaseline,
  type GazeReading,
  gazeDirection,
  readingFromLandmarks,
} from "./gaze";

/** A frontal face: eyes level at y 0.4, nose tip centred at 0.5, chin at 0.7, cheeks at 0.35/0.65. */
function face(noseX = 0.5, noseY = 0.52): { x: number; y: number; z: number }[] {
  const points = Array.from({ length: 478 }, () => ({ x: 0.5, y: 0.5, z: 0 }));
  points[1] = { x: noseX, y: noseY, z: 0 };
  points[234] = { x: 0.35, y: 0.45, z: 0 };
  points[454] = { x: 0.65, y: 0.45, z: 0 };
  points[33] = { x: 0.42, y: 0.4, z: 0 };
  points[263] = { x: 0.58, y: 0.4, z: 0 };
  points[152] = { x: 0.5, y: 0.7, z: 0 };
  return points;
}

const shapes = (values: Record<string, number> = {}) =>
  Object.entries(values).map(([categoryName, score]) => ({ categoryName, score }));

const AHEAD: GazeReading = { yaw: 0, pitch: 0.4, eyeX: 0, eyeY: 0 };

describe("readingFromLandmarks", () => {
  it("reads a frontal face as centred", () => {
    const reading = readingFromLandmarks(face(), shapes());
    expect(reading?.yaw).toBeCloseTo(0, 5);
    expect(reading?.pitch).toBeCloseTo(0.4, 5);
    expect(reading?.eyeX).toBe(0);
  });

  it("reads the nose toward the picture's right as the candidate turning to their left", () => {
    expect(readingFromLandmarks(face(0.6), shapes())?.yaw).toBeGreaterThan(0.2);
  });

  it("reads the eyes looking out of the left eye and into the right as looking left", () => {
    const reading = readingFromLandmarks(
      face(),
      shapes({ eyeLookOutLeft: 0.7, eyeLookInRight: 0.7 }),
    );
    expect(reading?.eyeX).toBeCloseTo(0.7, 5);
  });

  it("reads eyes looking down", () => {
    const reading = readingFromLandmarks(
      face(),
      shapes({ eyeLookDownLeft: 0.6, eyeLookDownRight: 0.8 }),
    );
    expect(reading?.eyeY).toBeCloseTo(0.7, 5);
  });

  it("can't read a face without its landmarks", () => {
    expect(readingFromLandmarks([], shapes())).toBeNull();
  });
});

describe("gazeDirection", () => {
  const rules = DEFAULT_GAZE_RULES;

  it("is centred while the candidate looks at the screen", () => {
    expect(gazeDirection(AHEAD, AHEAD, rules, false)).toBe("center");
  });

  it("names the side the head or the eyes turned to", () => {
    expect(gazeDirection({ ...AHEAD, yaw: 0.2 }, AHEAD, rules, false)).toBe("left");
    expect(gazeDirection({ ...AHEAD, yaw: -0.2 }, AHEAD, rules, false)).toBe("right");
    expect(gazeDirection({ ...AHEAD, eyeX: -0.6 }, AHEAD, rules, false)).toBe("right");
  });

  it("names a look down from the head or the eyes", () => {
    expect(gazeDirection({ ...AHEAD, pitch: 0.52 }, AHEAD, rules, false)).toBe("down");
    expect(gazeDirection({ ...AHEAD, eyeY: 0.6 }, AHEAD, rules, false)).toBe("down");
  });

  it("is relative to how this candidate sits, not to an ideal pose", () => {
    // A webcam above the screen: the candidate looking at the screen always looks a little down.
    const sitsLow: GazeReading = { yaw: 0.05, pitch: 0.5, eyeX: 0, eyeY: 0.3 };
    expect(gazeDirection(sitsLow, sitsLow, rules, false)).toBe("center");
  });

  it("clears only well back toward the centre (hysteresis)", () => {
    const nearEdge = { ...AHEAD, yaw: 0.11 };
    expect(gazeDirection(nearEdge, AHEAD, rules, false)).toBe("center");
    expect(gazeDirection(nearEdge, AHEAD, rules, true)).toBe("left");
  });
});

describe("GazeBaseline", () => {
  it("is the median of the first readings and stays put afterwards", () => {
    const baseline = new GazeBaseline(5);
    expect(baseline.value()).toBeNull();
    for (const yaw of [0.1, 0.0, 0.5, 0.05, 0.02]) baseline.add({ ...AHEAD, yaw });
    expect(baseline.value()?.yaw).toBeCloseTo(0.05, 5);
    baseline.add({ ...AHEAD, yaw: 0.9 });
    expect(baseline.value()?.yaw).toBeCloseTo(0.05, 5);
  });
});
