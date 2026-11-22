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

  it("prepares on one page, then runs the interview (owner, 2026-11-16)", () => {
    const steps: [FlowEvent, FlowState["screen"]][] = [
      [{ type: "interview-chosen", interviewId: "iv-1" }, "prepare"],
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

  it("goes back to the interviews from the page before the interview", () => {
    const prepare = run(...SIGNED_IN, { type: "interview-chosen", interviewId: "iv-1" });
    expect(transition(prepare, { type: "back" })).toEqual({
      screen: "interviews",
      profile: PROFILE,
    });
  });

  it("offers no way back once the interview is submitted (one attempt, C8-9)", () => {
    const completed = run(
      ...SIGNED_IN,
      { type: "interview-chosen", interviewId: "iv-1" },
      { type: "started" },
      { type: "completed" },
    );
    expect(transition(completed, { type: "back" })).toBe(completed);
    expect(transition(completed, { type: "interview-chosen", interviewId: "iv-1" })).toBe(
      completed,
    );
  });

  it("rejoins an interrupted interview from the list or straight after launch", () => {
    const chosen = run(...SIGNED_IN, { type: "reconnect-chosen", interviewId: "iv-1" });
    expect(chosen).toEqual({ screen: "reconnect", profile: PROFILE, interviewId: "iv-1" });
    expect(transition(chosen, { type: "started" })).toEqual({
      screen: "interview",
      profile: PROFILE,
      interviewId: "iv-1",
    });
    expect(transition(chosen, { type: "back" }).screen).toBe("interviews");
    const restored = run(
      { type: "release-checked", release: { status: "ok" } },
      { type: "session-restored", profile: PROFILE, interviewId: "iv-1" },
    );
    expect(restored).toEqual({ screen: "reconnect", profile: PROFILE, interviewId: "iv-1" });
    expect(
      transition(initialState, { type: "session-restored", profile: PROFILE, interviewId: "x" }),
    ).toBe(initialState);
  });

  it("doesn't leave a running interview by going back", () => {
    const interview = run(
      ...SIGNED_IN,
      { type: "interview-chosen", interviewId: "iv-1" },
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
    expect(transition(initialState, { type: "started" })).toEqual(initialState);
  });
});
