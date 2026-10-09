import { describe, expect, it } from "vitest";
import type { InterviewSummary } from "../native/commands";
import { formatCountdown, windowState } from "./interviews";

const INTERVIEW: InterviewSummary = {
  id: "iv-1",
  job_title: "Backend Engineer",
  status: "invited",
  starts_at: "2026-10-12T10:00:00Z",
  expires_at: "2026-10-12T18:00:00Z",
  duration_minutes: 45,
  third_eye: "optional",
  proctoring_level: "standard",
  coding: true,
};

describe("an interview's window", () => {
  it("counts down before it opens", () => {
    const state = windowState(INTERVIEW, Date.parse("2026-10-12T09:58:30Z"));
    expect(state).toEqual({ open: false, closed: false, msUntilOpen: 90_000 });
    expect(formatCountdown(state.msUntilOpen)).toBe("1 min 30 s");
  });

  it("is open between its start and its end", () => {
    expect(windowState(INTERVIEW, Date.parse("2026-10-12T10:00:00Z")).open).toBe(true);
  });

  it("is closed at its end", () => {
    expect(windowState(INTERVIEW, Date.parse("2026-10-12T18:00:00Z")).closed).toBe(true);
  });

  it("shows hours for long waits", () => {
    expect(formatCountdown(2 * 3600_000 + 5 * 60_000)).toBe("2 h 05 min");
  });
});
