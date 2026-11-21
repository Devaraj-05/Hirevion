import type { Profile, ReleaseState } from "../native/commands";

/**
 * The candidate's way through the app (PRD §26, master plan §6.4): version check → sign-in →
 * (code on a new device) → interviews → prepare → interview → completed. "Prepare" is one page
 * (product owner, 2026-11-16) holding what used to be separate screens: the briefing (§30's
 * instructions), camera and microphone, the system check (§29), the Terms and Conditions (§30,
 * §83) and the phone as a third eye (§6.4). A pure state machine, so every path is tested
 * without a window; the screens dispatch events and render the state.
 */

type Step = "prepare" | "interview" | "completed";

export type FlowState =
  | { screen: "launch" }
  | { screen: "update-required"; minimumVersion: string | null; downloadUrl: string | null }
  | { screen: "sign-in"; updateAvailable: boolean; notice?: "session-expired" }
  | { screen: "code"; challengeId: string; sentTo: string }
  | { screen: "interviews"; profile: Profile }
  | { screen: Step; profile: Profile; interviewId: string };

export type FlowEvent =
  | {
      type: "release-checked";
      release: Pick<ReleaseState, "status"> & Partial<ReleaseState>;
    }
  | { type: "code-required"; challengeId: string; sentTo: string }
  | { type: "signed-in"; profile: Profile }
  | { type: "profile-updated"; profile: Profile }
  | { type: "interview-chosen"; interviewId: string }
  | { type: "started" }
  | { type: "completed" }
  | { type: "back" }
  | { type: "signed-out" }
  | { type: "session-expired" };

export const initialState: FlowState = { screen: "launch" };

/** Each step's successor, and the event that moves to it. */
const NEXT: Partial<Record<FlowEvent["type"], [from: Step, to: Step]>> = {
  started: ["prepare", "interview"],
  completed: ["interview", "completed"],
};
/** "Back" leads to the interviews from these; never out of a running interview. */
const BACK_TO_INTERVIEWS: readonly FlowState["screen"][] = ["prepare", "completed"];

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
    case "interview-chosen":
      if (state.screen !== "interviews") return state;
      return { screen: "prepare", profile: state.profile, interviewId: event.interviewId };
    case "back":
      if (BACK_TO_INTERVIEWS.includes(state.screen) && "profile" in state) {
        return { screen: "interviews", profile: state.profile };
      }
      if (state.screen === "code") return { screen: "sign-in", updateAvailable: false };
      return state;
    default: {
      const step = NEXT[event.type];
      if (!step || state.screen !== step[0] || !("interviewId" in state)) return state;
      return { screen: step[1], profile: state.profile, interviewId: state.interviewId };
    }
  }
}
