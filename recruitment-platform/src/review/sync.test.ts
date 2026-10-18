import { describe, expect, it } from "vitest";
import {
  clock,
  eventOffset,
  filePosition,
  offsetFromFile,
  type TrackTiming,
  timelineEnd,
} from "./sync";

const ANCHOR = "2026-10-17T10:00:00.000Z";
const at = (seconds: number) => new Date(Date.parse(ANCHOR) + seconds * 1000).toISOString();

// Three 10 s segments; the middle one is missing, so the file holds 0-10 s and 10-20 s while the
// interview's clock ran 0-10 s and 20-30 s.
const MAPPED: TrackTiming = {
  started_at: at(0),
  duration_ms: 20_000,
  timeline: {
    segments: [
      { seq: 0, started_at: at(0), duration_ms: 10_000, file_offset_ms: 0 },
      { seq: 2, started_at: at(20), duration_ms: 10_000, file_offset_ms: 10_000 },
    ],
    gaps: [{ from_seq: 1, to_seq: 1 }],
  },
};
const WHOLE: TrackTiming = { started_at: at(5), duration_ms: 60_000, timeline: null };

describe("the review player's clock", () => {
  it("turns an interview offset into a position in each track's file", () => {
    expect(filePosition(ANCHOR, 4_000, MAPPED)).toBe(4_000);
    expect(filePosition(ANCHOR, 23_000, MAPPED)).toBe(13_000); // after the gap
    // A track recorded as one file counts from when it started.
    expect(filePosition(ANCHOR, 9_000, WHOLE)).toBe(4_000);
  });

  it("has no position where a track recorded nothing", () => {
    expect(filePosition(ANCHOR, 15_000, MAPPED)).toBeNull(); // the missing segment
    expect(filePosition(ANCHOR, 31_000, MAPPED)).toBeNull(); // after the last one
    expect(filePosition(ANCHOR, 2_000, WHOLE)).toBeNull(); // before it started
    expect(filePosition(ANCHOR, 70_000, WHOLE)).toBeNull(); // after its end
  });

  it("turns a position in a file back into an interview offset", () => {
    expect(offsetFromFile(ANCHOR, 13_000, MAPPED)).toBe(23_000);
    expect(offsetFromFile(ANCHOR, 4_000, WHOLE)).toBe(9_000);
    expect(offsetFromFile(ANCHOR, 99_000, MAPPED)).toBeNull();
  });

  it("measures an event from the interview's start", () => {
    expect(eventOffset(ANCHOR, at(150))).toBe(150_000);
    expect(eventOffset(null, at(150))).toBeNull();
    expect(eventOffset(ANCHOR, "not a time")).toBeNull();
  });

  it("ends where the last track ends", () => {
    expect(timelineEnd(ANCHOR, [MAPPED, WHOLE], 0)).toBe(65_000);
    expect(timelineEnd(ANCHOR, [], 45_000)).toBe(45_000);
  });

  it("writes a time as m:ss or h:mm:ss", () => {
    expect(clock(0)).toBe("0:00");
    expect(clock(62_400)).toBe("1:02");
    expect(clock(3_723_000)).toBe("1:02:03");
    expect(clock(-5)).toBe("0:00");
  });
});
