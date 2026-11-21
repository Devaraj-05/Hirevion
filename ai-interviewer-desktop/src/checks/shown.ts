import type { CheckName, CheckResult } from "./types";

/**
 * What the candidate sees of the system check (owner, 2026-11-21: "we only show Camera,
 * Microphone, Network and Display"). Every other check still runs and still goes to the server;
 * it shows only when it failed, because then the candidate has something to fix.
 */
export const SHOWN_CHECKS: readonly CheckName[] = ["camera", "microphone", "network", "displays"];

export function shownToCandidate(results: readonly CheckResult[]): CheckResult[] {
  const usable = results.filter(
    (result) => result.check !== "third_eye" && result.status !== "skipped",
  );
  const main = SHOWN_CHECKS.flatMap((name) => usable.filter((result) => result.check === name));
  const failed = usable.filter(
    (result) =>
      !(SHOWN_CHECKS as readonly string[]).includes(result.check) && result.status === "fail",
  );
  return [...main, ...failed];
}
