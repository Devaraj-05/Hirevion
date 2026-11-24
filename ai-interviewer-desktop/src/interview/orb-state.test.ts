import { describe, expect, it } from "vitest";
import { orbState } from "./orb-state";

describe("the interviewer's orb (C8-12)", () => {
  it("follows the interviewer's voice", () => {
    expect(orbState("speaking", "connected", false)).toBe("speaking");
    expect(orbState("thinking", "connected", false)).toBe("thinking");
    expect(orbState("listening", "connected", false)).toBe("listening");
  });

  it("turns to the candidate while they speak", () => {
    expect(orbState("listening", "connected", true)).toBe("candidate");
    // The interviewer talking over them still shows the interviewer.
    expect(orbState("speaking", "connected", true)).toBe("speaking");
  });

  it("rests while connecting, paused, ended or without voice", () => {
    expect(orbState("listening", "connecting", false)).toBe("connecting");
    expect(orbState("speaking", "reconnecting", false)).toBe("connecting");
    expect(orbState("listening", "off", true)).toBe("off");
    for (const voice of ["waiting", "paused", "ended", "error"] as const) {
      expect(orbState(voice, "connected", false)).toBe("resting");
    }
  });
});
