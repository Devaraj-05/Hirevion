import { describe, expect, it } from "vitest";
import { type FlowState, initialState, transition } from "./flow";

const PROFILE = {
  candidate: { id: "c-1", name: "Asha Rao", email: "asha@example.test", locale: "en-IN" },
  organization: { id: "o-1", name: "Acme", support_email: null },
  interviews: [],
};

function run(...events: Parameters<typeof transition>[1][]): FlowState {
  return events.reduce<FlowState>((state, event) => transition(state, event), initialState);
}

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

  it("runs the system check for the chosen interview and is ready when it passes", () => {
    const signedIn = run(
      { type: "release-checked", release: { status: "ok" } },
      { type: "signed-in", profile: PROFILE },
    );
    const checking = transition(signedIn, { type: "check-started", interviewId: "iv-1" });
    expect(checking).toEqual({ screen: "system-check", profile: PROFILE, interviewId: "iv-1" });
    expect(transition(checking, { type: "check-passed" })).toEqual({
      screen: "ready",
      profile: PROFILE,
      interviewId: "iv-1",
    });
    expect(transition(checking, { type: "back" })).toEqual({
      screen: "interviews",
      profile: PROFILE,
    });
  });

  it("returns to sign-in from anywhere after signing out or losing the session", () => {
    const ready = run(
      { type: "release-checked", release: { status: "ok" } },
      { type: "signed-in", profile: PROFILE },
      { type: "check-started", interviewId: "iv-1" },
    );
    expect(transition(ready, { type: "signed-out" })).toEqual({
      screen: "sign-in",
      updateAvailable: false,
    });
    expect(transition(ready, { type: "session-expired" })).toEqual({
      screen: "sign-in",
      updateAvailable: false,
      notice: "session-expired",
    });
  });

  it("ignores events that don't apply to the current screen", () => {
    expect(transition(initialState, { type: "check-passed" })).toEqual(initialState);
  });
});
