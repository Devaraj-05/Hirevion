import { describe, expect, it } from "vitest";
import { toFaceBoxes } from "./detections";
import { FpsMeter, summarize } from "./metrics";

const detection = (originX: number, originY: number, size: number, score: number) => ({
  boundingBox: { originX, originY, width: size, height: size, angle: 0 },
  categories: [{ score, index: 0, categoryName: "", displayName: "" }],
  keypoints: [],
});

describe("toFaceBoxes", () => {
  it("normalises MediaPipe's pixel boxes to the frame, best score first", () => {
    const boxes = toFaceBoxes(
      [detection(64, 36, 64, 0.7), detection(320, 90, 180, 0.95)],
      640,
      360,
    );
    expect(boxes).toEqual([
      { x: 0.5, y: 0.25, width: 180 / 640, height: 0.5, score: 0.95 },
      { x: 0.1, y: 0.1, width: 0.1, height: 64 / 360, score: 0.7 },
    ]);
  });

  it("clips a box that runs off the frame", () => {
    const [box] = toFaceBoxes([detection(-40, 300, 120, 0.9)], 640, 360);
    expect(box?.x).toBe(0);
    expect(box?.y).toBeCloseTo(300 / 360, 9);
    expect(box?.width).toBeCloseTo(80 / 640, 9);
    expect(box?.height).toBeCloseTo(60 / 360, 9);
  });

  it("drops detections without a box or a score, and handles an empty frame size", () => {
    expect(toFaceBoxes([{ categories: [] }], 640, 360)).toEqual([]);
    expect(toFaceBoxes([{ ...detection(0, 0, 10, 0.9), categories: [] }], 640, 360)).toEqual([]);
    expect(toFaceBoxes([detection(0, 0, 10, 0.9)], 0, 0)).toEqual([]);
  });
});

describe("metrics", () => {
  it("counts frames per second over a sliding window", () => {
    const meter = new FpsMeter(1_000);
    for (let t = 0; t < 2_000; t += 125) meter.tick(t);
    expect(meter.fps(1_900)).toBe(8);
    expect(meter.fps(5_000)).toBe(0);
  });

  it("summarises p50, p95 and the maximum", () => {
    expect(summarize([])).toBeNull();
    expect(summarize([4, 1, 3, 2, 5])).toEqual({ count: 5, p50: 3, p95: 4.8, max: 5 });
  });
});
