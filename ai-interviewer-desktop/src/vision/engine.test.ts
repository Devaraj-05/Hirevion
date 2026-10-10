import { describe, expect, it } from "vitest";
import { DEFAULT_VISION_CONFIG, type VisionConfig } from "./config";
import {
  flushEngine,
  initialEngineState,
  SignalEngine,
  type SignalEvent,
  stepEngine,
  toCameraEvent,
} from "./engine";
import { CAMERA_SIGNALS, type FaceBox, type FaceObservation, type FrameStats } from "./types";

const SCENE: FrameStats = { meanLuma: 0.45, stdLuma: 0.2, edgeEnergy: 0.08 };
const BLACK: FrameStats = { meanLuma: 0.01, stdLuma: 0.005, edgeEnergy: 0.001 };
const ONE: FaceBox[] = [{ x: 0.4, y: 0.3, width: 0.26, height: 0.35, score: 0.9 }];
const TWO: FaceBox[] = [...ONE, { x: 0.05, y: 0.3, width: 0.15, height: 0.2, score: 0.8 }];
const FAR: FaceBox[] = [{ x: 0.45, y: 0.4, width: 0.09, height: 0.12, score: 0.85 }];

type Frame = Omit<FaceObservation, "t">;
const present: Frame = { faces: ONE, frame: SCENE };
const absent: Frame = { faces: [], frame: SCENE };
const twoFaces: Frame = { faces: TWO, frame: SCENE };
const covered: Frame = { faces: [], frame: BLACK };
const far: Frame = { faces: FAR, frame: SCENE };

/** Frames every `step` ms: each segment lasts its duration, so `[[6000, absent]]` is 0..5900. */
function timeline(segments: Array<[number, Frame]>, step = 100, start = 0): FaceObservation[] {
  const frames: FaceObservation[] = [];
  let t = start;
  for (const [duration, frame] of segments) {
    const end = t + duration;
    for (; t < end; t += step) frames.push({ t, ...frame });
  }
  return frames;
}

function run(frames: FaceObservation[], config: VisionConfig = DEFAULT_VISION_CONFIG) {
  let state = initialEngineState();
  const events: SignalEvent[] = [];
  for (const frame of frames) {
    const step = stepEngine(state, frame, config);
    state = step.state;
    events.push(...step.events);
  }
  return { state, events };
}

const brief = (events: SignalEvent[]) =>
  events.map((event) => [event.signal, event.phase, event.level, event.durationMs]);

describe("FACE_ABSENT", () => {
  it("raises nothing for 4 s without a face", () => {
    expect(
      run(
        timeline([
          [4_000, absent],
          [10_000, present],
        ]),
      ).events,
    ).toEqual([]);
  });

  it("raises nothing at exactly 5 s, since the threshold is strictly more than 5 s", () => {
    expect(
      run(
        timeline([
          [5_100, absent],
          [10_000, present],
        ]),
      ).events,
    ).toEqual([]);
  });

  it("warns once the face has been gone more than 5 s, then ends with the full duration", () => {
    const { events } = run(
      timeline([
        [6_000, absent],
        [3_000, present],
      ]),
    );
    expect(brief(events)).toEqual([
      ["FACE_ABSENT", "started", "warning", 5_100],
      ["FACE_ABSENT", "ended", "warning", 6_000],
    ]);
    expect(events.every((event) => event.startedAtMs === 0)).toBe(true);
  });

  it("escalates to critical after 30 s", () => {
    const { events } = run(
      timeline([
        [31_000, absent],
        [3_000, present],
      ]),
    );
    expect(brief(events)).toEqual([
      ["FACE_ABSENT", "started", "warning", 5_100],
      ["FACE_ABSENT", "escalated", "critical", 30_100],
      ["FACE_ABSENT", "ended", "critical", 31_000],
    ]);
  });

  it("reports the episode's start, not the moment it crossed the threshold", () => {
    const { events } = run(
      timeline([
        [2_000, present],
        [7_000, absent],
        [2_000, present],
      ]),
    );
    expect(events.map((event) => event.startedAtMs)).toEqual([2_000, 2_000]);
    expect(events.at(-1)?.durationMs).toBe(7_000);
  });

  it("isn't restarted by a single missed frame, and counts it against confidence", () => {
    // A face flickers into view for one frame in ten.
    const flicker = Array.from({ length: 8 }, () => [
      [900, absent] as [number, Frame],
      [100, present] as [number, Frame],
    ]).flat();
    const { events } = run(timeline([...flicker, [2_000, present]]));
    expect(brief(events)).toEqual([
      ["FACE_ABSENT", "started", "warning", 5_100],
      ["FACE_ABSENT", "ended", "warning", 7_900],
    ]);
    expect(events[1]?.confidence).toBeCloseTo(72 / 79, 2);
  });
});

describe("MULTIPLE_FACES", () => {
  it("raises nothing for two faces during 2 s, then one", () => {
    expect(
      run(
        timeline([
          [2_000, twoFaces],
          [10_000, present],
        ]),
      ).events,
    ).toEqual([]);
  });

  it("raises a critical event after more than 3 s, with the second face's score", () => {
    const { events } = run(
      timeline([
        [3_500, twoFaces],
        [2_000, present],
      ]),
    );
    expect(brief(events)).toEqual([
      ["MULTIPLE_FACES", "started", "critical", 3_100],
      ["MULTIPLE_FACES", "ended", "critical", 3_500],
    ]);
    expect(events[0]?.confidence).toBeCloseTo(0.8, 6);
    expect(events[0]?.details).toMatchObject({ max_faces: 2, frames: 32 });
  });
});

describe("CAMERA_OBSTRUCTED", () => {
  it("raises a critical event after more than 5 s of a covered lens, and no FACE_ABSENT", () => {
    const { events } = run(
      timeline([
        [8_000, covered],
        [2_000, present],
      ]),
    );
    expect(brief(events)).toEqual([
      ["CAMERA_OBSTRUCTED", "started", "critical", 5_100],
      ["CAMERA_OBSTRUCTED", "ended", "critical", 8_000],
    ]);
    expect(events[0]?.details.mean_luma).toBeCloseTo(0.01, 6);
  });

  it("raises nothing for a 4 s cover", () => {
    expect(
      run(
        timeline([
          [4_000, covered],
          [5_000, present],
        ]),
      ).events,
    ).toEqual([]);
  });
});

describe("FACE_TOO_FAR", () => {
  it("warns after more than 10 s far from the camera, with the face's mean height", () => {
    const { events } = run(
      timeline([
        [12_000, far],
        [2_000, present],
      ]),
    );
    expect(brief(events)).toEqual([
      ["FACE_TOO_FAR", "started", "warning", 10_100],
      ["FACE_TOO_FAR", "ended", "warning", 12_000],
    ]);
    expect(events[0]?.details.face_height).toBeCloseTo(0.12, 6);
  });
});

describe("flapping and gaps", () => {
  it("merges fast flapping into one episode instead of spamming events", () => {
    const flapping = Array.from({ length: 100 }, () => [
      [300, absent] as [number, Frame],
      [300, present] as [number, Frame],
    ]).flat();
    const { events } = run(timeline([...flapping, [3_000, present]]));
    expect(brief(events).map(([signal, phase]) => `${signal} ${phase}`)).toEqual([
      "FACE_ABSENT started",
      "FACE_ABSENT escalated",
      "FACE_ABSENT ended",
    ]);
    expect(events[2]?.durationMs).toBe(59_700);
    expect(events[2]?.confidence).toBeCloseTo(0.5, 1);
  });

  it("isn't started or sustained by sparse detector misses", () => {
    // The detector misses the face in every fourth frame for a minute.
    const misses = Array.from({ length: 150 }, () => [
      [300, present] as [number, Frame],
      [100, absent] as [number, Frame],
    ]).flat();
    expect(run(timeline(misses)).events).toEqual([]);
  });

  it("raises nothing when every absence is shorter than the threshold", () => {
    const flapping = Array.from({ length: 15 }, () => [
      [2_000, absent] as [number, Frame],
      [2_000, present] as [number, Frame],
    ]).flat();
    expect(run(timeline(flapping)).events).toEqual([]);
  });

  it("ends an open episode at the last frame when frames stop arriving", () => {
    const frames = [...timeline([[6_000, absent]]), ...timeline([[1_000, present]], 100, 20_000)];
    const { events } = run(frames);
    expect(brief(events)).toEqual([
      ["FACE_ABSENT", "started", "warning", 5_100],
      ["FACE_ABSENT", "ended", "warning", 5_900],
    ]);
  });

  it("doesn't join two absences across a stall in the frames", () => {
    const frames = [
      ...timeline([[4_000, absent]]),
      ...timeline(
        [
          [4_000, absent],
          [2_000, present],
        ],
        100,
        10_000,
      ),
    ];
    expect(run(frames).events).toEqual([]);
  });

  it("ignores a frame that isn't newer than the last one", () => {
    let state = initialEngineState();
    state = stepEngine(state, { t: 1_000, ...absent }, DEFAULT_VISION_CONFIG).state;
    const step = stepEngine(state, { t: 900, ...absent }, DEFAULT_VISION_CONFIG);
    expect(step.events).toEqual([]);
    expect(step.state).toBe(state);
  });

  it("tracks overlapping signals independently", () => {
    // Two faces for 4 s, then the room empties for 6 s.
    const { events } = run(
      timeline([
        [4_000, twoFaces],
        [6_000, absent],
        [2_000, present],
      ]),
    );
    expect(brief(events)).toEqual([
      ["MULTIPLE_FACES", "started", "critical", 3_100],
      ["MULTIPLE_FACES", "ended", "critical", 4_000],
      ["FACE_ABSENT", "started", "warning", 5_100],
      ["FACE_ABSENT", "ended", "warning", 6_000],
    ]);
  });
});

describe("flushEngine", () => {
  it("ends every open episode when the module stops", () => {
    const { state } = run(timeline([[7_000, absent]]));
    const flushed = flushEngine(state);
    expect(brief(flushed.events)).toEqual([["FACE_ABSENT", "ended", "warning", 6_900]]);
    expect(flushEngine(flushed.state).events).toEqual([]);
  });

  it("drops a pending episode silently", () => {
    const { state } = run(timeline([[3_000, absent]]));
    expect(flushEngine(state).events).toEqual([]);
  });
});

describe("thresholds from config", () => {
  it("raises nothing for a signal with no threshold", () => {
    const config: VisionConfig = {
      ...DEFAULT_VISION_CONFIG,
      signals: { ...DEFAULT_VISION_CONFIG.signals, FACE_ABSENT: {} },
    };
    expect(run(timeline([[40_000, absent]]), config).events).toEqual([]);
  });

  it("follows the policy's thresholds", () => {
    const config: VisionConfig = {
      ...DEFAULT_VISION_CONFIG,
      signals: {
        ...DEFAULT_VISION_CONFIG.signals,
        FACE_ABSENT: { warn_after_ms: 2_000, critical_after_ms: 4_000 },
      },
    };
    const { events } = run(
      timeline([
        [5_000, absent],
        [2_000, present],
      ]),
      config,
    );
    expect(brief(events)).toEqual([
      ["FACE_ABSENT", "started", "warning", 2_100],
      ["FACE_ABSENT", "escalated", "critical", 4_100],
      ["FACE_ABSENT", "ended", "critical", 5_000],
    ]);
  });
});

describe("toCameraEvent", () => {
  const toIso = (t: number) => new Date(Date.UTC(2026, 9, 12, 5, 0, 0) + t).toISOString();

  it("builds the proctoring.md event without seq", () => {
    const { events } = run(
      timeline([
        [6_000, absent],
        [2_000, present],
      ]),
    );
    const [started] = events;
    if (!started) throw new Error("no event");
    const event = toCameraEvent(started, toIso);
    expect(event).toEqual({
      event: "FACE_ABSENT",
      source: "camera",
      started_at: "2026-10-12T05:00:00.000Z",
      duration_ms: 5_100,
      confidence: 1,
      evidence: [],
      details: { phase: "started", level: "warning", frames: 52 },
    });
    expect(event).not.toHaveProperty("seq");
  });

  it("rounds the duration to a whole millisecond and the confidence to two places", () => {
    const event = toCameraEvent(
      {
        signal: "MULTIPLE_FACES",
        phase: "started",
        level: "critical",
        startedAtMs: 12.4,
        durationMs: 3_100.6,
        confidence: 0.876_54,
        details: { frames: 31, max_faces: 3 },
      },
      toIso,
    );
    expect(event.duration_ms).toBe(3_101);
    expect(event.confidence).toBe(0.88);
    expect(event.details).toEqual({
      phase: "started",
      level: "critical",
      frames: 31,
      max_faces: 3,
    });
  });
});

describe("SignalEngine", () => {
  it("emits contract events through the callback, with the contract's names only", () => {
    const received: string[] = [];
    const engine = new SignalEngine(DEFAULT_VISION_CONFIG, {
      onEvent: (event) => received.push(`${event.event} ${event.details.phase}`),
      toServerIso: (t) => new Date(t).toISOString(),
    });
    for (const frame of timeline([
      [4_000, twoFaces],
      [6_000, covered],
      [7_000, absent],
    ])) {
      engine.push(frame);
    }
    expect(engine.active().sort()).toEqual(["FACE_ABSENT"]);
    engine.flush();
    expect(engine.active()).toEqual([]);
    expect(received).toEqual([
      "MULTIPLE_FACES started",
      "MULTIPLE_FACES ended",
      "CAMERA_OBSTRUCTED started",
      "CAMERA_OBSTRUCTED ended",
      "FACE_ABSENT started",
      "FACE_ABSENT ended",
    ]);
    const names = new Set<string>(CAMERA_SIGNALS);
    expect(received.every((line) => names.has(line.split(" ")[0] ?? ""))).toBe(true);
  });

  it("returns the events of each frame too", () => {
    const engine = new SignalEngine(DEFAULT_VISION_CONFIG);
    const events = timeline([[6_000, absent]]).flatMap((frame) => engine.push(frame));
    expect(events.map((event) => event.event)).toEqual(["FACE_ABSENT"]);
  });
});
