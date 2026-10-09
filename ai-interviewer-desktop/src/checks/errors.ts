import type { CheckResult } from "./types";

export type MediaDevice = "camera" | "microphone";

const PRIVACY_SETTINGS: Record<MediaDevice, string> = {
  camera: "ms-settings:privacy-webcam",
  microphone: "ms-settings:privacy-microphone",
};

/** What a failed `getUserMedia` means for the candidate, by the DOMException's name. */
export function describeMediaError(error: unknown, device: MediaDevice): string {
  switch (property(error, "name")) {
    case "NotAllowedError":
    case "SecurityError":
      return `Access to the ${device} is blocked. Allow it in Windows Settings (${PRIVACY_SETTINGS[device]}), then check again.`;
    case "NotFoundError":
    case "OverconstrainedError":
      return `No ${device} was found. Connect one, then check again.`;
    case "NotReadableError":
    case "AbortError":
      return `The ${device} is in use by another app or not responding. Close other apps that use it, then check again.`;
    default:
      return `The ${device} could not be started: ${property(error, "message") ?? String(error)}`;
  }
}

/** A string property of an error-like value (DOMExceptions included), if it has one. */
function property(error: unknown, key: "name" | "message"): string | undefined {
  if (typeof error === "object" && error !== null && key in error) {
    const value: unknown = (error as Record<string, unknown>)[key];
    return typeof value === "string" ? value : undefined;
  }
  return undefined;
}

/** The failed result for a device that couldn't be opened. */
export function mediaFailure(device: MediaDevice, error: unknown): CheckResult {
  return {
    check: device,
    status: "fail",
    value: "not available",
    detail: describeMediaError(error, device),
  };
}
