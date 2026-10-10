import { describe, expect, it } from "vitest";
import { type FlowEvent, type FlowState, initialState, transition } from "./flow";

const PROFILE = {
  candidate: { id: "c-1", name: "Asha Rao", email: "asha@example.test", locale: "en-IN" },
  organization: { id: "o-1", name: "Acme", support_email: null },
  interviews: [],
};

function run(...events: FlowEvent[]): FlowState {
  return events.reduce<FlowState>((state, event) => transition(state, event), initialState);
}

const SIGNED_IN: FlowEvent[] = [
  { type: "release-checked", release: { status: "ok" } },
  { type: "signed-in", profile: PROFILE },
];

describe("the launch flow (PRD §26)", () => {
  it("starts by checking the app version", () => {
    expect(initialState).toEqual({ screen: "launch" });
  });

  it("stops at the update screen when the version is too old", () => {
    const state = run({
      type: "release-checked",
      release: { status: "update-required", minimum_version: "2.0.0", download_url: "https://x" },
    });
    expect(state).toEqual({
      screen: "update-required",
      minimumVersion: "2.0.0",
      downloadUrl: "https://x",
    });
  });

  it("goes to sign-in when the version is fine, even with an optional update", () => {
    expect(run({ type: "release-checked", release: { status: "update-available" } })).toEqual({
      screen: "sign-in",
      updateAvailable: true,
    });
  });

  it("asks for the emailed code on a new device, then lists the interviews", () => {
    const state = run(
      { type: "release-checked", release: { status: "ok" } },
      { type: "code-required", challengeId: "ch-1", sentTo: "a***@example.test" },
    );
    expect(state).toEqual({ screen: "code", challengeId: "ch-1", sentTo: "a***@example.test" });
    expect(transition(state, { type: "signed-in", profile: PROFILE })).toEqual({
      screen: "interviews",
      profile: PROFILE,
    });
  });

  it("walks briefing, system check, consent and ready, in that order, to the interview", () => {
    const steps: [FlowEvent, FlowState["screen"]][] = [
      [{ type: "interview-chosen", interviewId: "iv-1" }, "briefing"],
      [{ type: "briefing-read" }, "system-check"],
      [{ type: "check-passed" }, "consent"],
      [{ type: "consented" }, "ready"],
      [{ type: "started" }, "interview"],
      [{ type: "completed" }, "completed"],
    ];
    let state = run(...SIGNED_IN);
    for (const [event, screen] of steps) {
      state = transition(state, event);
      expect(state.screen).toBe(screen);
      expect(state).toMatchObject({ profile: PROFILE, interviewId: "iv-1" });
    }
  });

  it("goes back to the interviews from any step before the interview starts", () => {
    const consent = run(
      ...SIGNED_IN,
      { type: "interview-chosen", interviewId: "iv-1" },
      { type: "briefing-read" },
      { type: "check-passed" },
    );
    expect(transition(consent, { type: "back" })).toEqual({
      screen: "interviews",
      profile: PROFILE,
    });
  });

  it("doesn't leave a running interview by going back", () => {
    const interview = run(
      ...SIGNED_IN,
      { type: "interview-chosen", interviewId: "iv-1" },
      { type: "briefing-read" },
      { type: "check-passed" },
      { type: "consented" },
      { type: "started" },
    );
    expect(transition(interview, { type: "back" })).toBe(interview);
  });

  it("returns to sign-in from anywhere after signing out or losing the session", () => {
    const checking = run(...SIGNED_IN, { type: "interview-chosen", interviewId: "iv-1" });
    expect(transition(checking, { type: "signed-out" })).toEqual({
      screen: "sign-in",
      updateAvailable: false,
    });
    expect(transition(checking, { type: "session-expired" })).toEqual({
      screen: "sign-in",
      updateAvailable: false,
      notice: "session-expired",
    });
  });

  it("ignores events that don't apply to the current screen", () => {
    expect(transition(initialState, { type: "check-passed" })).toEqual(initialState);
  });
});
