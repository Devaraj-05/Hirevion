import type { Profile, ReleaseState } from "../native/commands";

/**
 * The launch flow (PRD §26, master plan §6.4) up to "Ready": version check → sign-in → (code on
 * a new device) → interviews → system check → ready. A pure state machine, so every path is
 * tested without a window; the screens dispatch events and render the state.
 */

export type FlowState =
  | { screen: "launch" }
  | { screen: "update-required"; minimumVersion: string | null; downloadUrl: string | null }
  | { screen: "sign-in"; updateAvailable: boolean; notice?: "session-expired" }
  | { screen: "code"; challengeId: string; sentTo: string }
  | { screen: "interviews"; profile: Profile }
  | { screen: "system-check"; profile: Profile; interviewId: string }
  | { screen: "ready"; profile: Profile; interviewId: string };

export type FlowEvent =
  | {
      type: "release-checked";
      release: Pick<ReleaseState, "status"> & Partial<ReleaseState>;
    }
  | { type: "code-required"; challengeId: string; sentTo: string }
  | { type: "signed-in"; profile: Profile }
  | { type: "profile-updated"; profile: Profile }
  | { type: "check-started"; interviewId: string }
  | { type: "check-passed" }
  | { type: "back" }
  | { type: "signed-out" }
  | { type: "session-expired" };

export const initialState: FlowState = { screen: "launch" };

export function transition(state: FlowState, event: FlowEvent): FlowState {
  switch (event.type) {
    case "signed-out":
      return { screen: "sign-in", updateAvailable: false };
    case "session-expired":
      return { screen: "sign-in", updateAvailable: false, notice: "session-expired" };
    case "release-checked":
      if (state.screen !== "launch") return state;
      return event.release.status === "update-required"
        ? {
            screen: "update-required",
            minimumVersion: event.release.minimum_version ?? null,
            downloadUrl: event.release.download_url ?? null,
          }
        : { screen: "sign-in", updateAvailable: event.release.status === "update-available" };
    case "code-required":
      if (state.screen !== "sign-in") return state;
      return { screen: "code", challengeId: event.challengeId, sentTo: event.sentTo };
    case "signed-in":
      if (state.screen !== "sign-in" && state.screen !== "code") return state;
      return { screen: "interviews", profile: event.profile };
    case "profile-updated":
      return "profile" in state ? { ...state, profile: event.profile } : state;
    case "check-started":
      if (state.screen !== "interviews") return state;
      return { screen: "system-check", profile: state.profile, interviewId: event.interviewId };
    case "check-passed":
      if (state.screen !== "system-check") return state;
      return { screen: "ready", profile: state.profile, interviewId: state.interviewId };
    case "back":
      if (state.screen === "system-check" || state.screen === "ready") {
        return { screen: "interviews", profile: state.profile };
      }
      if (state.screen === "code") return { screen: "sign-in", updateAvailable: false };
      return state;
  }
}
