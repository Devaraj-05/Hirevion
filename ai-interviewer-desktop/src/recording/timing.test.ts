import { describe, expect, it } from "vitest";
import {
  BoundaryIndex,
  planRotation,
  SEGMENT_MS,
  SegmentPlanner,
  type SegmentTiming,
  ServerTime,
  TrackClock,
  TrackTimeline,
} from "./timing";

const TIME_ORIGIN_MS = 1_700_000_000_000;

/** A deterministic pseudo-random sequence in [0, 1). */
function random(seed: number): () => number {
  let state = seed >>> 0 || 1;
  return () => {
    state ^= state << 13;
    state ^= state >>> 17;
    state ^= state << 5;
    return (state >>> 0) / 4_294_967_296;
  };
}

describe("ServerTime", () => {
  it("turns performance.now() into server milliseconds", () => {
    const time = new ServerTime(TIME_ORIGIN_MS, 250);
    expect(time.fromPerfMs(1_000)).toBe(TIME_ORIGIN_MS + 1_250);
    time.setOffset(-40);
    expect(time.fromPerfMs(1_000)).toBe(TIME_ORIGIN_MS + 960);
  });
});

describe("TrackClock", () => {
  it("maps a track's timestamps through the earliest arrival", () => {
    const clock = new TrackClock(new ServerTime(TIME_ORIGIN_MS, 250));
    expect(clock.ready).toBe(false);
    // Camera timestamps run on their own clock, here starting at 5,000 s.
    clock.observe(5_000_000_000, 1_000);
    expect(clock.ready).toBe(true);
    expect(clock.toServerMs(5_000_000_000)).toBe(TIME_ORIGIN_MS + 1_000 + 250);
    expect(clock.toServerMs(5_010_000_000)).toBe(TIME_ORIGIN_MS + 11_000 + 250);
  });

  it("uses the least-delayed sample of the window, ignoring arrival jitter", () => {
    const clock = new TrackClock(new ServerTime(TIME_ORIGIN_MS, 0));
    clock.observe(0, 30); // arrived 30 ms after capture
    clock.observe(66_667, 66.667 + 5); // arrived 5 ms after capture
    clock.observe(133_333, 133.333 + 40);
    expect(clock.toServerMs(0)).toBeCloseTo(TIME_ORIGIN_MS + 5, 6);
  });

  it("follows a drifting device clock window by window", () => {
    const clock = new TrackClock(new ServerTime(TIME_ORIGIN_MS, 0));
    clock.observe(0, 10);
    clock.settle();
    // An hour later the device clock is 200 ms behind the system clock.
    clock.observe(3_600_000_000, 3_600_200 + 10);
    clock.settle();
    expect(clock.toServerMs(3_600_000_000)).toBeCloseTo(TIME_ORIGIN_MS + 3_600_210, 6);
  });

  it("refuses to map before the first sample", () => {
    const clock = new TrackClock(new ServerTime(TIME_ORIGIN_MS, 0));
    expect(() => clock.toServerMs(0)).toThrow();
  });
});

describe("SegmentPlanner", () => {
  const planner = new SegmentPlanner(TIME_ORIGIN_MS, SEGMENT_MS);

  it("numbers 10-second windows from 0", () => {
    expect(planner.seqFor(TIME_ORIGIN_MS)).toBe(0);
    expect(planner.seqFor(TIME_ORIGIN_MS + 9_999)).toBe(0);
    expect(planner.seqFor(TIME_ORIGIN_MS + 10_000)).toBe(1);
    expect(planner.seqFor(TIME_ORIGIN_MS + 125_000)).toBe(12);
  });

  it("puts samples from before the origin in the first window", () => {
    expect(planner.seqFor(TIME_ORIGIN_MS - 50)).toBe(0);
  });

  it("knows where each window starts", () => {
    expect(planner.windowStartMs(3)).toBe(TIME_ORIGIN_MS + 30_000);
  });
});

describe("TrackTimeline", () => {
  it("starts a segment at each window and reports the finished one", () => {
    const time = new ServerTime(TIME_ORIGIN_MS, 0);
    const timeline = new TrackTimeline(time, new SegmentPlanner(TIME_ORIGIN_MS, SEGMENT_MS));
    const frameUs = 66_667;
    const finished: SegmentTiming[] = [];
    const starts: number[] = [];
    for (let frame = 0; frame < 15 * 25; frame += 1) {
      const ts = frame * frameUs;
      const placed = timeline.place(ts, frameUs, ts / 1_000 + 3);
      if (placed.starts) {
        starts.push(placed.seq);
      }
      if (placed.finished) {
        finished.push(placed.finished);
      }
    }
    const last = timeline.finish();
    expect(starts).toEqual([0, 1, 2]);
    expect(finished.map((s) => s.seq)).toEqual([0, 1]);
    expect(finished[0]?.startedAtMs).toBeCloseTo(TIME_ORIGIN_MS + 3, 3);
    expect(finished[0]?.durationMs).toBe(10_000);
    expect(finished[1]?.startedAtMs).toBeCloseTo(TIME_ORIGIN_MS + 10_003, 0);
    expect(last?.seq).toBe(2);
    expect(timeline.finish()).toBeNull();
  });

  it("keeps the sequence increasing across a pause longer than a window", () => {
    const timeline = new TrackTimeline(
      new ServerTime(TIME_ORIGIN_MS, 0),
      new SegmentPlanner(TIME_ORIGIN_MS, SEGMENT_MS),
    );
    timeline.place(0, 20_000, 1);
    const resumed = timeline.place(35_000_000, 20_000, 35_001);
    expect(resumed).toMatchObject({ seq: 3, starts: true });
    expect(resumed.finished?.seq).toBe(0);
  });
});

describe("BoundaryIndex", () => {
  it("finds the segment an encoded chunk belongs to", () => {
    const index = new BoundaryIndex();
    index.add(1_000, 0);
    index.add(10_001_000, 1);
    index.add(20_001_000, 2);
    expect(index.seqAt(1_000)).toBe(0);
    expect(index.seqAt(10_000_999)).toBe(0);
    expect(index.seqAt(10_001_000)).toBe(1);
    expect(index.seqAt(25_000_000)).toBe(2);
    expect(index.seqAt(0)).toBe(0);
    index.forgetBefore(2);
    expect(index.seqAt(10_001_000)).toBe(2);
  });
});

describe("planRotation", () => {
  it("stops each MediaRecorder at the next window boundary", () => {
    expect(planRotation(TIME_ORIGIN_MS + 2_500, TIME_ORIGIN_MS, SEGMENT_MS, -1)).toEqual({
      seq: 0,
      stopInMs: 7_500,
    });
  });

  it("folds a sliver before a boundary into the next window", () => {
    expect(planRotation(TIME_ORIGIN_MS + 9_800, TIME_ORIGIN_MS, SEGMENT_MS, -1)).toEqual({
      seq: 1,
      stopInMs: 10_200,
    });
  });

  it("never repeats a seq", () => {
    expect(planRotation(TIME_ORIGIN_MS + 10_050, TIME_ORIGIN_MS, SEGMENT_MS, 1)).toEqual({
      seq: 2,
      stopInMs: 9_950,
    });
  });
});

describe("drift", () => {
  interface Track {
    name: string;
    /** Device timestamp of a sample at true time t (ms since the recording origin). */
    deviceUs: (trueMs: number) => number;
    sampleMs: number;
  }

  /** Simulates an hour of capture and returns |started_at − true start| for every segment. */
  function simulate(track: Track, seed: number, fixedAnchor: boolean): number[] {
    const next = random(seed);
    // The server is 1,234 ms ahead of this PC; recording starts at performance.now() = 5 s.
    const time = new ServerTime(TIME_ORIGIN_MS, 1_234);
    const startPerfMs = 5_000;
    const planner = new SegmentPlanner(time.fromPerfMs(startPerfMs), SEGMENT_MS);
    const timeline = new TrackTimeline(time, planner, { fixedAnchor });
    const trueStart = new Map<number, number>();
    const errors: number[] = [];
    const check = (segment: SegmentTiming | null) => {
      if (segment) {
        errors.push(Math.abs(segment.startedAtMs - (trueStart.get(segment.seq) ?? Number.NaN)));
      }
    };
    // Count samples rather than add up durations: a float sum would add a stray sample.
    const samples = Math.round(3_600_000 / track.sampleMs);
    for (let sample = 0; sample < samples; sample += 1) {
      const t = sample * track.sampleMs;
      const latency = 5 + next() * 40;
      const placed = timeline.place(
        track.deviceUs(t),
        track.sampleMs * 1_000,
        startPerfMs + t + latency,
      );
      if (placed.starts) {
        trueStart.set(placed.seq, time.fromPerfMs(startPerfMs + t));
      }
      check(placed.finished);
    }
    check(timeline.finish());
    return errors;
  }

  const camera: Track = {
    name: "camera",
    // System capture clock, 40 ppm fast.
    deviceUs: (t) => 7_000_000_000 + t * 1_000 * (1 + 40e-6),
    sampleMs: 1_000 / 15,
  };
  const mic: Track = {
    name: "mic",
    // Sample-count clock from stream start, 60 ppm slow.
    deviceUs: (t) => t * 1_000 * (1 - 60e-6),
    sampleMs: 20,
  };

  it("keeps every segment start within 100 ms of the truth for an hour", () => {
    for (const [track, seed] of [
      [camera, 1],
      [mic, 2],
    ] as const) {
      const errors = simulate(track, seed, false);
      expect(errors.length).toBe(360);
      expect(Math.max(...errors), track.name).toBeLessThan(100);
    }
  });

  it("puts camera and mic segment n within 100 ms of each other", () => {
    const cameraErrors = simulate(camera, 3, false);
    const micErrors = simulate(mic, 4, false);
    const worst = Math.max(...cameraErrors.map((e, i) => e + (micErrors[i] ?? 0)));
    expect(worst).toBeLessThan(100);
  });

  it("would drift past 100 ms with a single anchor (why each window is re-anchored)", () => {
    const errors = simulate(mic, 5, true);
    expect(Math.max(...errors)).toBeGreaterThan(100);
  });
});
