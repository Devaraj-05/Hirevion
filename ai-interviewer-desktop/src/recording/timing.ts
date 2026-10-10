/**
 * Where camera and microphone segments sit on the interview's timeline.
 *
 * Every segment is stamped with its first sample's time in **server** milliseconds
 * (`started_at` in the recordings contract), so the media worker can line the camera, the
 * microphone and every screen up within 100 ms. Three clocks meet here:
 *
 * - each media track's own timestamps (µs): the camera on the system capture clock, the
 *   microphone often counting samples from the stream's start, each drifting a little;
 * - `performance.now()` (ms), with `performance.timeOrigin` turning it into local epoch time;
 * - the server's clock, `serverOffsetMs` ahead of this PC (measured in Rust with `GET /time`).
 *
 * A track's timestamps are tied to `performance.now()` by the least-delayed sample of each
 * 10-second window (arrival time minus timestamp), so arrival jitter is ignored and a drifting
 * device clock is followed window by window instead of accumulating.
 */

export const SEGMENT_MS = 10_000;
/** The longest segment the server accepts. */
export const MAX_SEGMENT_MS = 60_000;

/** Converts `performance.now()` readings into server milliseconds. */
export class ServerTime {
  constructor(
    private readonly timeOriginMs: number,
    private offsetMs: number,
  ) {}

  /** Uses `performance.timeOrigin` and the offset Rust reports. */
  static fromPerformance(serverOffsetMs: number): ServerTime {
    return new ServerTime(performance.timeOrigin, serverOffsetMs);
  }

  /** A new clock sync moved the server offset. */
  setOffset(offsetMs: number): void {
    this.offsetMs = offsetMs;
  }

  fromPerfMs(perfMs: number): number {
    return this.timeOriginMs + perfMs + this.offsetMs;
  }

  nowMs(): number {
    return this.fromPerfMs(performance.now());
  }
}

/** Maps one media track's timestamps (µs) onto the server clock. */
export class TrackClock {
  /** The least delay seen in the open window: `performance.now()` µs minus timestamp µs. */
  private window: number | null = null;
  private settled: number | null = null;

  constructor(
    private readonly time: ServerTime,
    /** Keep the first sample's anchor forever (only to show why windows are needed). */
    private readonly fixedAnchor = false,
  ) {}

  get ready(): boolean {
    return this.window !== null || this.settled !== null;
  }

  /** A sample with this timestamp arrived at this `performance.now()`. */
  observe(timestampUs: number, arrivalPerfMs: number): void {
    const offsetUs = arrivalPerfMs * 1_000 - timestampUs;
    if (this.fixedAnchor) {
      this.settled ??= offsetUs;
      return;
    }
    this.window = this.window === null ? offsetUs : Math.min(this.window, offsetUs);
  }

  /** Closes the window: its least-delayed sample becomes the anchor until the next one. */
  settle(): void {
    if (this.window !== null) {
      this.settled = this.window;
      this.window = null;
    }
  }

  toServerMs(timestampUs: number): number {
    const anchorUs = this.window ?? this.settled;
    if (anchorUs === null) {
      throw new Error("no sample observed yet");
    }
    return this.time.fromPerfMs((timestampUs + anchorUs) / 1_000);
  }
}

/** Numbers fixed windows from the recording's start, shared by every track. */
export class SegmentPlanner {
  constructor(
    readonly originServerMs: number,
    readonly segmentMs: number = SEGMENT_MS,
  ) {}

  seqFor(serverMs: number): number {
    return Math.max(0, Math.floor((serverMs - this.originServerMs) / this.segmentMs));
  }

  windowStartMs(seq: number): number {
    return this.originServerMs + seq * this.segmentMs;
  }
}

/** A finished segment's place on the timeline. */
export interface SegmentTiming {
  seq: number;
  /** The first sample, in server milliseconds. */
  startedAtMs: number;
  durationMs: number;
}

export interface Placement {
  /** The segment this sample belongs to. */
  seq: number;
  /** This sample opens the segment (a video encoder must make it a keyframe). */
  starts: boolean;
  /** The segment this sample closed, if any. */
  finished: SegmentTiming | null;
}

interface OpenSegment {
  seq: number;
  firstUs: number;
  endUs: number;
}

/** Follows one track's samples, window by window, and reports each finished segment. */
export class TrackTimeline {
  private readonly clock: TrackClock;
  private open: OpenSegment | null = null;
  private lastSeq = -1;

  constructor(
    time: ServerTime,
    private readonly planner: SegmentPlanner,
    options: { fixedAnchor?: boolean } = {},
  ) {
    this.clock = new TrackClock(time, options.fixedAnchor ?? false);
  }

  /** Places a sample that arrived at `arrivalPerfMs` (its `performance.now()`). */
  place(timestampUs: number, durationUs: number, arrivalPerfMs: number): Placement {
    this.clock.observe(timestampUs, arrivalPerfMs);
    const floor = this.open ? this.open.seq : this.lastSeq + 1;
    const seq = Math.max(this.planner.seqFor(this.clock.toServerMs(timestampUs)), floor);
    const end = timestampUs + Math.max(0, durationUs);
    if (this.open && seq === this.open.seq) {
      this.open.endUs = Math.max(this.open.endUs, end);
      return { seq, starts: false, finished: null };
    }
    const finished = this.close();
    this.open = { seq, firstUs: timestampUs, endUs: end };
    return { seq, starts: true, finished };
  }

  /** Closes the open segment (at stop). */
  finish(): SegmentTiming | null {
    return this.close();
  }

  private close(): SegmentTiming | null {
    const open = this.open;
    if (!open) {
      return null;
    }
    this.open = null;
    this.lastSeq = open.seq;
    // The window covers the whole segment now, so its anchor is the best estimate.
    const startedAtMs = this.clock.toServerMs(open.firstUs);
    this.clock.settle();
    const durationMs = Math.min(
      MAX_SEGMENT_MS,
      Math.max(1, Math.round((open.endUs - open.firstUs) / 1_000)),
    );
    return { seq: open.seq, startedAtMs, durationMs };
  }
}

/**
 * Which segment an encoded chunk belongs to, from the timestamps where segments started on
 * the encoder's input (encoders may merge or split input frames, as Opus does).
 */
export class BoundaryIndex {
  private boundaries: { timestampUs: number; seq: number }[] = [];

  add(timestampUs: number, seq: number): void {
    this.boundaries.push({ timestampUs, seq });
  }

  seqAt(timestampUs: number): number {
    let found = this.boundaries[0]?.seq ?? 0;
    for (const boundary of this.boundaries) {
      if (boundary.timestampUs <= timestampUs) {
        found = boundary.seq;
      } else {
        break;
      }
    }
    return found;
  }

  /** Drops boundaries of segments before `seq` (they are finished). */
  forgetBefore(seq: number): void {
    this.boundaries = this.boundaries.filter((boundary) => boundary.seq >= seq);
  }
}

/** A MediaRecorder started this close to a boundary records into the next window instead. */
const MIN_SLICE_MS = 500;

/**
 * When a (re)started MediaRecorder should stop so its file ends on a window boundary, and
 * which seq it records. Seqs only ever increase.
 */
export function planRotation(
  nowServerMs: number,
  originServerMs: number,
  segmentMs: number,
  lastSeq: number,
): { seq: number; stopInMs: number } {
  let seq = Math.max(0, Math.floor((nowServerMs - originServerMs) / segmentMs));
  let stopInMs = originServerMs + (seq + 1) * segmentMs - nowServerMs;
  if (stopInMs < MIN_SLICE_MS) {
    seq += 1;
    stopInMs += segmentMs;
  }
  return { seq: Math.max(seq, lastSeq + 1), stopInMs };
}
