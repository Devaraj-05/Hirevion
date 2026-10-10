import type { Profile, ReleaseState } from "../native/commands";

/**
 * The candidate's way through the app (PRD §26, master plan §6.4): version check → sign-in →
 * (code on a new device) → interviews → briefing (§30's instructions) → system check (§29) →
 * consent (§30, §83) → ready → interview → completed. A pure state machine, so every path is
 * tested without a window; the screens dispatch events and render the state.
 */

type Step = "briefing" | "system-check" | "consent" | "ready" | "interview" | "completed";

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
  | { type: "briefing-read" }
  | { type: "check-passed" }
  | { type: "consented" }
  | { type: "started" }
  | { type: "completed" }
  | { type: "back" }
  | { type: "signed-out" }
  | { type: "session-expired" };

export const initialState: FlowState = { screen: "launch" };

/** Each step's successor, and the event that moves to it. */
const NEXT: Partial<Record<FlowEvent["type"], [from: Step, to: Step]>> = {
  "briefing-read": ["briefing", "system-check"],
  "check-passed": ["system-check", "consent"],
  consented: ["consent", "ready"],
  started: ["ready", "interview"],
  completed: ["interview", "completed"],
};
const BEFORE_THE_INTERVIEW: readonly FlowState["screen"][] = [
  "briefing",
  "system-check",
  "consent",
  "ready",
  "completed",
];

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
      return { screen: "briefing", profile: state.profile, interviewId: event.interviewId };
    case "back":
      if (BEFORE_THE_INTERVIEW.includes(state.screen) && "profile" in state) {
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
