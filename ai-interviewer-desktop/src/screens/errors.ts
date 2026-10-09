import { isCommandError } from "../native/commands";

/** The message key for a failed command; unknown codes fall back to a generic message. */
export const KNOWN_ERRORS = [
  "invalid-credentials",
  "account-locked",
  "account-disabled",
  "app-update-required",
  "no-interview",
  "job-closed",
  "interview-not-available",
  "interview-expired",
  "interview-not-open",
  "otp-invalid",
  "otp-expired",
  "otp-attempts-exceeded",
  "network",
] as const;
export type ErrorKey = (typeof KNOWN_ERRORS)[number] | "unknown";

export function errorKey(error: unknown): ErrorKey {
  if (!isCommandError(error)) return "unknown";
  return (KNOWN_ERRORS as readonly string[]).includes(error.code)
    ? (error.code as ErrorKey)
    : "unknown";
}

/** Errors that mean the session is gone and the candidate must sign in again. */
export function isSessionLost(error: unknown): boolean {
  return (
    isCommandError(error) &&
    ["signed-out", "refresh-invalid", "refresh-reused", "otp-attempts-exceeded"].includes(
      error.code,
    )
  );
}
