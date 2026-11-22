import { describe, expect, it } from "vitest";
import type { InterviewSummary } from "../native/commands";
import { formatRejoin, listed, offerFor, rejoinable, rejoinSecondsLeft } from "./attempt";

const NOW = Date.parse("2026-11-22T10:00:00Z");

function interview(overrides: Partial<InterviewSummary> = {}): InterviewSummary {
  return {
    id: "iv-1",
    job_title: "Backend Engineer",
    status: "invited",
    starts_at: "2026-11-22T09:00:00Z",
    expires_at: "2026-11-22T18:00:00Z",
    duration_minutes: 30,
    third_eye: "optional",
    proctoring_level: "standard",
    coding: false,
    attempt: "available",
    reconnect_until: null,
    ...overrides,
  };
}

const PROFILE = {
  candidate: { id: "c-1", name: "Asha Rao", email: "asha@example.test", locale: "en-IN" },
  organization: { id: "o-1", name: "Acme", support_email: null },
};

describe("one attempt (C8-9)", () => {
  it("offers what the server allows", () => {
    expect(offerFor(interview(), NOW)).toBe("start");
    expect(offerFor(interview({ starts_at: "2026-11-22T11:00:00Z" }), NOW)).toBe("wait");
    expect(offerFor(interview({ attempt: "not_open" }), NOW)).toBe("wait");
    expect(offerFor(interview({ status: "interrupted", attempt: "reconnect" }), NOW)).toBe(
      "rejoin",
    );
    expect(offerFor(interview({ status: "in_progress", attempt: "elsewhere" }), NOW)).toBe(
      "elsewhere",
    );
  });

  it("finds the interview to rejoin after a crash", () => {
    const rejoin = interview({ id: "iv-2", status: "interrupted", attempt: "reconnect" });
    expect(rejoinable({ ...PROFILE, interviews: [interview(), rejoin] })).toBe(rejoin);
    expect(rejoinable({ ...PROFILE, interviews: [interview()] })).toBeUndefined();
  });

  it("counts down the reconnect window", () => {
    const dropped = interview({ reconnect_until: "2026-11-22T10:01:42Z" });
    expect(rejoinSecondsLeft(dropped, NOW)).toBe(102);
    expect(formatRejoin(102)).toBe("1:42");
    expect(rejoinSecondsLeft(dropped, NOW + 200_000)).toBe(0);
    expect(rejoinSecondsLeft(interview(), NOW)).toBeNull();
  });

  it("keeps a running interview listed past its window's end", () => {
    const late = NOW + 9 * 3_600_000;
    expect(listed(interview(), late)).toBe(false);
    expect(listed(interview({ status: "in_progress", attempt: "reconnect" }), late)).toBe(true);
  });
});
