/**
 * The time left (C8-12): amber from five minutes, red from two, said aloud to a screen reader at
 * five and at one. The app ticks it itself; the agent's refresh (every few seconds) only moves it
 * when it disagrees by more than `SLACK_SECONDS`, so the clock never jumps by a second.
 */

export const LOW_SECONDS = 300;
export const CRITICAL_SECONDS = 120;
export const SLACK_SECONDS = 2;

export type ClockTone = "normal" | "low" | "critical";

export function clockTone(seconds: number): ClockTone {
  if (seconds <= CRITICAL_SECONDS) return "critical";
  if (seconds <= LOW_SECONDS) return "low";
  return "normal";
}

/** The clock after the server's word: the local tick unless it has drifted. */
export function reconcile(local: number, server: number, slack: number = SLACK_SECONDS): number {
  // A clock that ran out while the server still has time takes the server's word.
  if (local <= 0 && server > 0) return server;
  return Math.abs(local - server) <= slack ? local : server;
}

/** The minutes to announce as the clock goes from `previous` to `next`, or null. */
export function announcement(previous: number, next: number): 5 | 1 | null {
  // A jump past both marks announces the nearer one.
  if (previous > 60 && next <= 60) return 1;
  if (previous > LOW_SECONDS && next <= LOW_SECONDS) return 5;
  return null;
}
