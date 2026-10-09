/** A check's outcome, spelt as the Rust `hv_system_check::Status` serialises it. */
export type Status = "pass" | "warn" | "fail" | "skipped";

/**
 * One check's result: the shape of the Rust `hv_system_check::CheckResult` and of an item in
 * the system-check upload's `results` (docs/api/contracts/interview-session.md). `value` is
 * what was measured; `detail` says what is wrong and what to do. Both are absent when unused.
 */
export interface CheckResult {
  check: string;
  status: Status;
  value?: string;
  detail?: string;
}

/** The upload's check names in the contract's order: PRD §29's eleven, plus two. */
export const CHECK_NAMES = [
  "camera",
  "microphone",
  "speaker",
  "screen_capture",
  "network",
  "cpu",
  "memory",
  "disk",
  "displays",
  "privacy",
  "third_eye",
  "media_foundation",
  "webview2",
] as const;

export type CheckName = (typeof CHECK_NAMES)[number];

export function isCheckName(name: string): name is CheckName {
  return (CHECK_NAMES as readonly string[]).includes(name);
}
