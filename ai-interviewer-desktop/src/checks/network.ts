import type { CheckResult } from "./types";

/** Round trips to the API (through Rust): under 300 ms passes, under 1 s warns. LiveKit's own
 * connection check runs when the interview starts, once there is a room token (SP-08b). */
export const NETWORK_PASS_MS = 300;
export const NETWORK_WARN_MS = 1_000;

export function networkResult(rttMs: number | null): CheckResult {
  if (rttMs === null) {
    return {
      check: "network",
      status: "fail",
      detail: "Can't reach the interview service. Check your internet connection.",
    };
  }
  const value = `${Math.round(rttMs)} ms to the interview service`;
  if (rttMs < NETWORK_PASS_MS) return { check: "network", status: "pass", value };
  if (rttMs < NETWORK_WARN_MS) {
    return {
      check: "network",
      status: "warn",
      value,
      detail: "Your connection is slow; the interview may lag.",
    };
  }
  return {
    check: "network",
    status: "fail",
    value,
    detail: "Your connection is too slow for a video interview.",
  };
}
