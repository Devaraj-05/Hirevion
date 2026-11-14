/**
 * The phone step's rules (contract third-eye.md; ADR-0040). The server judges the third eye
 * from its own view of the phone's camera; the desktop shows the pairing and waits for it.
 */

export type ThirdEyeMode = "off" | "optional" | "required";

/** What the candidate sees: a code to scan, the phone starting, connected, reconnecting after
 * a lock, or a code that is spent and needs replacing. */
export type PhoneState = "waiting" | "starting" | "connected" | "reconnecting" | "new-code";

export function phoneState(status: string): PhoneState {
  switch (status) {
    case "redeemed":
      return "starting";
    case "connected":
      return "connected";
    case "disconnected":
      // The phone page unpublishes on a lock and comes back by itself: no new code.
      return "reconnecting";
    case "expired":
    case "revoked":
      return "new-code";
    default:
      return "waiting";
  }
}

/** The system check failed on the third eye alone: the phone isn't paired yet, so the check
 * waits for the phone step, which sends it again once the phone is connected. */
export function onlyThirdEyeFailed(failedMandatory: readonly string[]): boolean {
  return failedMandatory.length > 0 && failedMandatory.every((check) => check === "third_eye");
}
