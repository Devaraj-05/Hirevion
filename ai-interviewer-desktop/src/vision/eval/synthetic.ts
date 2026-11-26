import type { CameraSignal, FaceBox, FaceObservation, FrameStats } from "../types";
import type { LabelledTimeline } from "./evaluate";

/** A small seeded PRNG (mulberry32): the same seed always gives the same clips. */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4_294_967_296;
  };
}

/** What the scene holds during a segment: the candidate alone, or one of the signals. */
export type Scene = "present" | CameraSignal;

export interface SyntheticOptions {
  fps: number;
  /** Each frame arrives up to this many ms early or late. */
  jitterMs: number;
  /** The detector misses a face that's there. */
  missRate: number;
  /** The detector misses the second face. */
  secondMissRate: number;
  /** The detector sees a second face that isn't there. */
  spuriousSecondRate: number;
  /** The detector sees a face in an empty frame. */
  spuriousFaceRate: number;
  /** SP-15b: the landmarker reads a look away as centred, or a centred look as away. */
  gazeMissRate: number;
  spuriousGazeRate: number;
  /** SP-15b: the object detector misses a phone in view, or sees one that isn't there. */
  phoneMissRate: number;
  spuriousPhoneRate: number;
}

/** Imperfections a little worse than ADR-0007's fake-camera run, so the engine is exercised. */
export const SYNTHETIC_DEFAULTS: SyntheticOptions = {
  fps: 8,
  jitterMs: 25,
  missRate: 0.04,
  secondMissRate: 0.12,
  spuriousSecondRate: 0.02,
  spuriousFaceRate: 0.02,
  gazeMissRate: 0.1,
  spuriousGazeRate: 0.04,
  phoneMissRate: 0.15,
  spuriousPhoneRate: 0.01,
};

const between = (random: () => number, low: number, high: number) => low + (high - low) * random();

function face(random: () => number, height: number, x = 0.4): FaceBox {
  return {
    x: x + between(random, -0.02, 0.02),
    y: 0.25 + between(random, -0.02, 0.02),
    width: height * 0.75,
    height: height + between(random, -0.01, 0.01),
    score: between(random, 0.75, 0.97),
  };
}

function frameFor(
  scene: Scene,
  random: () => number,
  options: SyntheticOptions,
): Omit<FaceObservation, "t"> {
  const room: FrameStats = {
    meanLuma: between(random, 0.35, 0.5),
    stdLuma: between(random, 0.15, 0.25),
    edgeEnergy: between(random, 0.05, 0.1),
  };
  const missed = () => random() < options.missRate;
  const glance = () =>
    random() < options.spuriousGazeRate ? (random() < 0.5 ? "left" : "down") : "center";
  const noPhone = () =>
    random() < options.spuriousPhoneRate ? between(random, 0.5, 0.6) : between(random, 0, 0.3);
  switch (scene) {
    case "present": {
      if (missed()) return { faces: [], frame: room, phone: noPhone() };
      const faces = [face(random, 0.35)];
      if (random() < options.spuriousSecondRate) {
        faces.push({ ...face(random, 0.08, 0.05), score: between(random, 0.6, 0.7) });
      }
      return { faces, frame: room, gaze: glance(), phone: noPhone() };
    }
    case "GAZE_DEVIATION": {
      if (missed()) return { faces: [], frame: room };
      const away = random() < options.gazeMissRate ? "center" : "down";
      return { faces: [face(random, 0.35)], frame: room, gaze: away, phone: noPhone() };
    }
    case "PHONE_DETECTED": {
      const phone =
        random() < options.phoneMissRate ? between(random, 0, 0.3) : between(random, 0.55, 0.9);
      return { faces: [face(random, 0.35)], frame: room, gaze: "center", phone };
    }
    case "FACE_ABSENT":
      return random() < options.spuriousFaceRate
        ? { faces: [{ ...face(random, 0.1, 0.7), score: 0.55 }], frame: room }
        : { faces: [], frame: room };
    case "MULTIPLE_FACES": {
      if (missed()) return { faces: [], frame: room };
      const faces = [face(random, 0.35)];
      if (random() >= options.secondMissRate) faces.push(face(random, 0.22, 0.05));
      return { faces, frame: room };
    }
    case "CAMERA_OBSTRUCTED":
      return {
        faces: [],
        frame: {
          meanLuma: between(random, 0.005, 0.04),
          stdLuma: between(random, 0.002, 0.02),
          edgeEnergy: between(random, 0.001, 0.008),
        },
      };
    case "FACE_TOO_FAR":
      return missed() || missed()
        ? { faces: [], frame: room }
        : { faces: [face(random, 0.11)], frame: room };
    case "FACE_TOO_CLOSE":
      return missed() ? { faces: [], frame: room } : { faces: [face(random, 0.74)], frame: room };
  }
}

/**
 * A clip from a script of scenes and their durations: frames at `fps` with jitter and detector
 * mistakes, and a label for every segment that isn't "present".
 */
export function syntheticClip(
  clip: string,
  script: ReadonlyArray<readonly [Scene, number]>,
  random: () => number,
  options: SyntheticOptions = SYNTHETIC_DEFAULTS,
): LabelledTimeline {
  const observations: FaceObservation[] = [];
  const labels: LabelledTimeline["labels"] = [];
  const period = 1_000 / options.fps;
  let segmentStart = 0;
  let tick = 0;
  for (const [scene, duration] of script) {
    const segmentEnd = segmentStart + duration;
    for (; tick * period < segmentEnd; tick += 1) {
      const t = Math.max(0, tick * period + between(random, -options.jitterMs, options.jitterMs));
      const previous = observations.at(-1)?.t ?? -1;
      observations.push({ t: Math.max(t, previous + 1), ...frameFor(scene, random, options) });
    }
    if (scene !== "present") {
      labels.push({ signal: scene, start_ms: segmentStart, end_ms: segmentEnd });
    }
    segmentStart = segmentEnd;
  }
  return { clip, observations, labels };
}

const S = 1_000;

/**
 * The synthetic labelled set: each signal with episodes too short to report, near the
 * threshold and well past it (absence past critical), between stretches of the candidate alone.
 */
export function syntheticSet(seed = 7): LabelledTimeline[] {
  const random = mulberry32(seed);
  const scripts: Array<[string, Array<readonly [Scene, number]>]> = [
    [
      "absences",
      [
        ["present", 10 * S],
        ["FACE_ABSENT", 3 * S],
        ["present", 10 * S],
        ["FACE_ABSENT", 8 * S],
        ["present", 10 * S],
        ["FACE_ABSENT", 35 * S],
        ["present", 10 * S],
        ["FACE_ABSENT", 12 * S],
        ["present", 10 * S],
      ],
    ],
    [
      "visitors",
      [
        ["present", 10 * S],
        ["MULTIPLE_FACES", 2 * S],
        ["present", 10 * S],
        ["MULTIPLE_FACES", 5 * S],
        ["present", 10 * S],
        ["MULTIPLE_FACES", 12 * S],
        ["present", 10 * S],
      ],
    ],
    [
      "camera",
      [
        ["present", 10 * S],
        ["CAMERA_OBSTRUCTED", 4 * S],
        ["present", 10 * S],
        ["CAMERA_OBSTRUCTED", 9 * S],
        ["present", 10 * S],
      ],
    ],
    [
      "distance",
      [
        ["present", 10 * S],
        ["FACE_TOO_FAR", 6 * S],
        ["present", 10 * S],
        ["FACE_TOO_FAR", 15 * S],
        ["present", 10 * S],
        ["FACE_TOO_CLOSE", 16 * S],
        ["present", 10 * S],
      ],
    ],
    [
      "glances",
      [
        ["present", 10 * S],
        ["GAZE_DEVIATION", 4 * S],
        ["present", 10 * S],
        ["GAZE_DEVIATION", 15 * S],
        ["present", 10 * S],
        ["GAZE_DEVIATION", 25 * S],
        ["present", 10 * S],
      ],
    ],
    [
      "phones",
      [
        ["present", 10 * S],
        ["PHONE_DETECTED", 1 * S],
        ["present", 10 * S],
        ["PHONE_DETECTED", 4 * S],
        ["present", 10 * S],
        ["PHONE_DETECTED", 9 * S],
        ["present", 10 * S],
      ],
    ],
    ["a quiet interview", [["present", 120 * S]]],
  ];
  return scripts.map(([clip, script]) => syntheticClip(clip, script, random));
}
