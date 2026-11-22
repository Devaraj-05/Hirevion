import type { InterviewSummary, Profile } from "../native/commands";

/**
 * One attempt per interview (C8-9, product owner 2026-11-22). The server decides what the
 * candidate may do with each interview (`attempt`); the app only follows it.
 */

/** What the interviews list offers for an interview. */
export type Offer = "start" | "rejoin" | "wait" | "elsewhere";

/** The interview the candidate may rejoin now, if any (the one reconnect). */
export function rejoinable(profile: Profile): InterviewSummary | undefined {
  return profile.interviews.find((interview) => interview.attempt === "reconnect");
}

/** Whole seconds left to rejoin; null while the server set no deadline (it hasn't seen the drop
 * yet, so the interview is still running). */
export function rejoinSecondsLeft(
  interview: Pick<InterviewSummary, "reconnect_until">,
  nowMs: number,
): number | null {
  if (!interview.reconnect_until) return null;
  return Math.max(0, Math.floor((Date.parse(interview.reconnect_until) - nowMs) / 1000));
}

/** "1:42": the time left to rejoin. */
export function formatRejoin(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export function offerFor(interview: InterviewSummary, nowMs: number): Offer {
  switch (interview.attempt) {
    case "reconnect":
      return "rejoin";
    case "elsewhere":
      return "elsewhere";
    case "not_open":
      return "wait";
    default:
      return Date.parse(interview.starts_at) <= nowMs ? "start" : "wait";
  }
}

/** Whether the list shows the interview: a running one stays listed past its window's end (it
 * may finish), the others until their window closes. */
export function listed(interview: InterviewSummary, nowMs: number): boolean {
  if (interview.attempt === "reconnect" || interview.attempt === "elsewhere") return true;
  return nowMs < Date.parse(interview.expires_at);
}
