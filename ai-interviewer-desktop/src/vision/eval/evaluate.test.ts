import { describe, expect, it } from "vitest";
import { DEFAULT_VISION_CONFIG } from "../config";
import type { FaceObservation } from "../types";
import {
  EXIT_TARGETS,
  evaluate,
  meetsTargets,
  parseLabelledTimeline,
  predictedEpisodes,
  scoreIntervals,
} from "./evaluate";
import { mulberry32, syntheticSet } from "./synthetic";

const span = (start: number, end: number) => ({ start, end });

describe("scoreIntervals", () => {
  // FACE_ABSENT's first threshold is 5 s; the tolerance is 500 ms.
  const score = (predicted: ReturnType<typeof span>[], labels: ReturnType<typeof span>[]) =>
    scoreIntervals(predicted, labels, 5_000, 500);

  it("matches a reported episode to the label it overlaps", () => {
    expect(score([span(1_000, 9_000)], [span(1_000, 9_000)])).toEqual({
      tp: 1,
      fp: 0,
      fn: 0,
      ignored: 0,
    });
  });

  it("counts a missed reportable label as a false negative", () => {
    expect(score([], [span(0, 8_000)])).toMatchObject({ tp: 0, fn: 1 });
  });

  it("counts an episode with no label as a false positive", () => {
    expect(score([span(0, 6_000)], [])).toMatchObject({ tp: 0, fp: 1 });
  });

  it("counts an episode over a label too short to report as a false positive", () => {
    expect(score([span(0, 5_200)], [span(0, 4_000)])).toEqual({ tp: 0, fp: 1, fn: 0, ignored: 0 });
  });

  it("neither rewards nor punishes labels within the tolerance of the threshold", () => {
    expect(score([span(0, 5_200)], [span(0, 5_300)])).toEqual({ tp: 0, fp: 0, fn: 0, ignored: 1 });
    expect(score([], [span(0, 4_800)])).toEqual({ tp: 0, fp: 0, fn: 0, ignored: 0 });
  });

  it("matches one-to-one, so a split episode costs a false positive", () => {
    expect(score([span(0, 6_000), span(7_000, 20_000)], [span(0, 20_000)])).toEqual({
      tp: 1,
      fp: 1,
      fn: 0,
      ignored: 0,
    });
  });

  it("matches two labels with two episodes, in order", () => {
    expect(
      score([span(0, 6_000), span(20_000, 30_000)], [span(0, 6_000), span(20_000, 30_000)]),
    ).toMatchObject({ tp: 2, fp: 0, fn: 0 });
  });
});

describe("predictedEpisodes", () => {
  it("gives each reported episode's span, including one still open at the end", () => {
    const frames: FaceObservation[] = [];
    for (let t = 0; t < 7_000; t += 100) frames.push({ t, faces: [], frame: null });
    expect(predictedEpisodes(frames, DEFAULT_VISION_CONFIG)).toEqual([
      { signal: "FACE_ABSENT", start: 0, end: 6_900 },
    ]);
  });
});

describe("evaluate", () => {
  it("computes precision and recall per signal, 1 when nothing was expected or raised", () => {
    const frames: FaceObservation[] = [];
    for (let t = 0; t < 8_000; t += 100) frames.push({ t, faces: [], frame: null });
    const report = evaluate([
      {
        clip: "one absence, one missed multiple-faces label",
        observations: frames,
        labels: [
          { signal: "FACE_ABSENT", start_ms: 0, end_ms: 8_000 },
          { signal: "MULTIPLE_FACES", start_ms: 1_000, end_ms: 6_000 },
        ],
      },
    ]);
    expect(report.clips).toBe(1);
    expect(report.signals.FACE_ABSENT).toEqual({
      tp: 1,
      fp: 0,
      fn: 0,
      ignored: 0,
      precision: 1,
      recall: 1,
    });
    expect(report.signals.MULTIPLE_FACES).toMatchObject({ fn: 1, precision: 1, recall: 0 });
    expect(report.signals.CAMERA_OBSTRUCTED).toMatchObject({ precision: 1, recall: 1 });
  });

  it("names the signals that miss their targets", () => {
    const frames: FaceObservation[] = [{ t: 0, faces: [], frame: null }];
    const report = evaluate([
      {
        clip: "missed",
        observations: frames,
        labels: [{ signal: "MULTIPLE_FACES", start_ms: 0, end_ms: 9_000 }],
      },
    ]);
    expect(meetsTargets(report, EXIT_TARGETS)).toEqual({
      ok: false,
      failures: ["MULTIPLE_FACES recall 0.00 < 0.90"],
    });
  });
});

describe("the synthetic labelled set", () => {
  it("is reproducible from its seed", () => {
    const first = mulberry32(42);
    const second = mulberry32(42);
    expect([first(), first(), first()]).toEqual([second(), second(), second()]);
    expect(syntheticSet(7)).toEqual(syntheticSet(7));
    expect(syntheticSet(7)).not.toEqual(syntheticSet(8));
  });

  it("covers every signal with reportable and too-short episodes", () => {
    const labels = syntheticSet(7).flatMap((clip) => clip.labels);
    for (const signal of [
      "FACE_ABSENT",
      "MULTIPLE_FACES",
      "CAMERA_OBSTRUCTED",
      "FACE_TOO_FAR",
      "FACE_TOO_CLOSE",
    ]) {
      expect(labels.some((label) => label.signal === signal)).toBe(true);
    }
    const absences = labels.filter((label) => label.signal === "FACE_ABSENT");
    expect(absences.some((label) => label.end_ms - label.start_ms < 4_000)).toBe(true);
    expect(absences.some((label) => label.end_ms - label.start_ms > 30_000)).toBe(true);
  });

  it("meets the exit targets for absent and multiple faces across seeds", () => {
    for (const seed of [1, 7, 42, 2026]) {
      const report = evaluate(syntheticSet(seed));
      expect(meetsTargets(report, EXIT_TARGETS)).toEqual({ ok: true, failures: [] });
      for (const score of Object.values(report.signals)) {
        expect(score.precision).toBeGreaterThanOrEqual(0.9);
        expect(score.recall).toBeGreaterThanOrEqual(0.9);
      }
    }
  });
});

describe("parseLabelledTimeline", () => {
  const valid = {
    version: 1,
    clip: "desk-01",
    observations: [
      { t: 0, faces: [{ x: 0.4, y: 0.3, width: 0.2, height: 0.3, score: 0.9 }], frame: null },
      { t: 100, faces: [], frame: { meanLuma: 0.4, stdLuma: 0.2, edgeEnergy: 0.07 } },
    ],
    labels: [{ signal: "FACE_ABSENT", start_ms: 100, end_ms: 8_000 }],
  };

  it("reads a clip file", () => {
    const timeline = parseLabelledTimeline(valid);
    expect(timeline.clip).toBe("desk-01");
    expect(timeline.observations).toHaveLength(2);
    expect(timeline.labels).toEqual(valid.labels);
  });

  it("rejects another version, an unknown signal, a bad face and a backwards label", () => {
    expect(() => parseLabelledTimeline({ ...valid, version: 2 })).toThrow(/version/);
    expect(() =>
      parseLabelledTimeline({
        ...valid,
        labels: [{ signal: "GAZE_DEVIATION", start_ms: 0, end_ms: 1 }],
      }),
    ).toThrow(/signal/);
    expect(() =>
      parseLabelledTimeline({ ...valid, observations: [{ t: 0, faces: [{ x: 1 }], frame: null }] }),
    ).toThrow(/face/);
    expect(() =>
      parseLabelledTimeline({
        ...valid,
        labels: [{ signal: "FACE_ABSENT", start_ms: 9, end_ms: 1 }],
      }),
    ).toThrow(/label/);
    expect(() => parseLabelledTimeline(null)).toThrow();
  });
});

// Real labelled clips: drop `{ version: 1, clip, observations, labels }` files here (see the
// SP-15a plan). They hold boxes and luminance numbers only, never video.
const CLIPS = import.meta.glob<unknown>("./clips/*.json", { eager: true, import: "default" });

describe("the labelled clips in src/vision/eval/clips", () => {
  const files = Object.values(CLIPS);
  it.skipIf(files.length === 0)("meet the exit targets", () => {
    const report = evaluate(files.map((json) => parseLabelledTimeline(json)));
    expect(meetsTargets(report, EXIT_TARGETS).failures).toEqual([]);
  });
});
