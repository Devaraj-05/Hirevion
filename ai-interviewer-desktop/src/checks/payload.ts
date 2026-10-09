import { CHECK_NAMES, type CheckName, type CheckResult, isCheckName } from "./types";

/** Mandatory until interview policies arrive (SP-14); then the interview's policy decides. */
export const DEFAULT_MANDATORY: readonly CheckName[] = [
  "camera",
  "microphone",
  "screen_capture",
  "media_foundation",
];

/** The body of `POST /interviews/{id}/system-checks`. */
export interface SystemCheckPayload {
  app_version: string;
  os: string;
  results: CheckResult[];
}

export interface PayloadInput {
  appVersion: string;
  /** From the `native_checks` command, plus the screen-capture probe. */
  native: readonly CheckResult[];
  /** From the webview: camera, microphone, speaker, network, webview2. */
  web: readonly CheckResult[];
  /** Overrides the native `os` check's value. */
  os?: string;
}

/**
 * Merges the native and webview results into the upload body.
 *
 * - Results follow the contract's order; checks it doesn't list follow, in arrival order.
 * - When a check appears twice, the later one wins (web after native), so a retried check
 *   replaces its first attempt.
 * - The native `os` check isn't a contract check: its value becomes the body's `os`.
 * - `third_eye` is `skipped` until phone pairing exists (SP-13).
 */
export function buildPayload(input: PayloadInput): SystemCheckPayload {
  const byName = new Map<string, CheckResult>();
  for (const result of [...input.native, ...input.web]) {
    byName.set(result.check, { ...result });
  }
  const os = input.os ?? byName.get("os")?.value ?? "unknown";
  byName.delete("os");
  if (!byName.has("third_eye")) {
    byName.set("third_eye", { check: "third_eye", status: "skipped" });
  }
  const listed = CHECK_NAMES.flatMap((name) => {
    const result = byName.get(name);
    return result ? [result] : [];
  });
  const unlisted = [...byName.values()].filter((result) => !isCheckName(result.check));
  return { app_version: input.appVersion, os, results: [...listed, ...unlisted] };
}

/**
 * The mandatory checks that are missing or didn't pass, in the policy's order. The server
 * applies the same rule (`failed_mandatory`); this lets the app say so before uploading.
 * When a check appears twice, its later result counts, as in `buildPayload`.
 */
export function missingMandatory(
  results: readonly CheckResult[],
  mandatory: readonly string[] = DEFAULT_MANDATORY,
): string[] {
  const latest = new Map(results.map((result) => [result.check, result.status]));
  return mandatory.filter((name) => latest.get(name) !== "pass");
}
