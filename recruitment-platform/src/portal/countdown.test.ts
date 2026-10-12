import { describe, expect, it } from "vitest";
import { countdownParts, windowPhase } from "./countdown";

const HOUR = 3_600_000;

describe("windowPhase", () => {
  const opens = Date.parse("2026-10-20T04:30:00Z");
  const closes = Date.parse("2026-10-21T18:29:00Z");

  it("is before, open or closed against the window", () => {
    expect(windowPhase(opens - 1, opens, closes)).toEqual({ phase: "before", ms: 1 });
    expect(windowPhase(opens, opens, closes)).toEqual({ phase: "open", ms: closes - opens });
    expect(windowPhase(closes, opens, closes)).toEqual({ phase: "closed", ms: 0 });
  });
});

describe("countdownParts", () => {
  it("keeps the two largest units that matter", () => {
    expect(countdownParts(26 * HOUR + 5 * 60_000)).toEqual([
      ["days", 1],
      ["hours", 2],
    ]);
    expect(countdownParts(3 * HOUR + 5 * 60_000 + 9_000)).toEqual([
      ["hours", 3],
      ["minutes", 5],
    ]);
    expect(countdownParts(2 * HOUR)).toEqual([["hours", 2]]);
    expect(countdownParts(45_000)).toEqual([["seconds", 45]]);
    expect(countdownParts(0)).toEqual([["seconds", 0]]);
  });
});
