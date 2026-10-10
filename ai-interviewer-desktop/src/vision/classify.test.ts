import { describe, expect, it } from "vitest";
import { classifyFrame, NO_SIGNALS } from "./classify";
import { DEFAULT_VISION_CONFIG } from "./config";
import type { CameraSignal, FaceBox, FaceObservation, FrameStats } from "./types";

const SCENE: FrameStats = { meanLuma: 0.45, stdLuma: 0.2, edgeEnergy: 0.08 };
const BLACK: FrameStats = { meanLuma: 0.01, stdLuma: 0.005, edgeEnergy: 0.001 };

function face(height: number, score = 0.9, x = 0.4, y = 0.3): FaceBox {
  return { x, y, width: height * 0.75, height, score };
}

function observe(faces: FaceBox[], frame: FrameStats | null = SCENE): FaceObservation {
  return { t: 0, faces, frame };
}

function onSignals(
  observation: FaceObservation,
  wasOn: Partial<Record<CameraSignal, boolean>> = {},
) {
  const reading = classifyFrame(observation, DEFAULT_VISION_CONFIG, { ...NO_SIGNALS, ...wasOn });
  return Object.entries(reading.signals)
    .filter(([, signal]) => signal.on)
    .map(([name]) => name);
}

describe("classifyFrame", () => {
  it("raises nothing for one face at a normal distance", () => {
    expect(onSignals(observe([face(0.35)]))).toEqual([]);
  });

  it("calls a frame with no face FACE_ABSENT", () => {
    const reading = classifyFrame(observe([]), DEFAULT_VISION_CONFIG, NO_SIGNALS);
    expect(reading.signals.FACE_ABSENT).toEqual({ on: true, confidence: 1 });
    expect(onSignals(observe([]))).toEqual(["FACE_ABSENT"]);
    expect(reading.faces).toBe(0);
  });

  it("calls a frame with no face FACE_ABSENT when it couldn't be measured", () => {
    expect(onSignals(observe([], null))).toEqual(["FACE_ABSENT"]);
  });

  it("calls a black frame with no face CAMERA_OBSTRUCTED instead of FACE_ABSENT", () => {
    expect(onSignals(observe([], BLACK))).toEqual(["CAMERA_OBSTRUCTED"]);
  });

  it("never calls a frame obstructed while a face is visible in it", () => {
    expect(onSignals(observe([face(0.35)], BLACK))).toEqual([]);
  });

  it("calls a second confident face MULTIPLE_FACES, with its score as the confidence", () => {
    const reading = classifyFrame(
      observe([face(0.35, 0.95), face(0.2, 0.8, 0.1)]),
      DEFAULT_VISION_CONFIG,
      NO_SIGNALS,
    );
    expect(reading.signals.MULTIPLE_FACES).toEqual({ on: true, confidence: 0.8 });
    expect(reading.faces).toBe(2);
  });

  it("doesn't judge distance while several faces are in view", () => {
    expect(onSignals(observe([face(0.1, 0.95), face(0.1, 0.9, 0.1)]))).toEqual(["MULTIPLE_FACES"]);
  });

  it("needs a stronger second face to start MULTIPLE_FACES than to keep it (hysteresis)", () => {
    const weak = observe([face(0.35), face(0.2, 0.55, 0.1)]);
    expect(onSignals(weak)).toEqual([]);
    expect(onSignals(weak, { MULTIPLE_FACES: true })).toEqual(["MULTIPLE_FACES"]);
    const weaker = observe([face(0.35), face(0.2, 0.45, 0.1)]);
    expect(onSignals(weaker, { MULTIPLE_FACES: true })).toEqual([]);
  });

  it("ignores a second face too small to be a person in the room", () => {
    const reading = classifyFrame(
      observe([face(0.35), face(0.03, 0.9, 0.1)]),
      DEFAULT_VISION_CONFIG,
      NO_SIGNALS,
    );
    expect(reading.signals.MULTIPLE_FACES.on).toBe(false);
    expect(reading.faces).toBe(1);
  });

  it("calls a small face FACE_TOO_FAR, with hysteresis on the way back", () => {
    expect(onSignals(observe([face(0.14)]))).toEqual(["FACE_TOO_FAR"]);
    expect(onSignals(observe([face(0.16)]))).toEqual([]);
    expect(onSignals(observe([face(0.16)]), { FACE_TOO_FAR: true })).toEqual(["FACE_TOO_FAR"]);
    expect(onSignals(observe([face(0.18)]), { FACE_TOO_FAR: true })).toEqual([]);
  });

  it("calls a large face FACE_TOO_CLOSE, with hysteresis on the way back", () => {
    expect(onSignals(observe([face(0.66)]))).toEqual(["FACE_TOO_CLOSE"]);
    expect(onSignals(observe([face(0.64)]))).toEqual([]);
    expect(onSignals(observe([face(0.64)]), { FACE_TOO_CLOSE: true })).toEqual(["FACE_TOO_CLOSE"]);
    expect(onSignals(observe([face(0.62)]), { FACE_TOO_CLOSE: true })).toEqual([]);
  });

  it("reports the face's score as distance confidence, and the measurements", () => {
    const reading = classifyFrame(observe([face(0.12, 0.7)]), DEFAULT_VISION_CONFIG, NO_SIGNALS);
    expect(reading.signals.FACE_TOO_FAR).toEqual({ on: true, confidence: 0.7 });
    expect(reading.faceHeight).toBe(0.12);
    expect(reading.meanLuma).toBe(SCENE.meanLuma);
  });
});
