import type { UpdateProgress } from "../native/commands";
import { isCommandError } from "../native/commands";

/** The update screen's state: nothing started, a download or install running, or a failure. */
export type UpdateState =
  | { step: "idle" }
  | { step: "checking" }
  | { step: "downloading"; downloaded: number; total: number | null }
  | { step: "installing" }
  | { step: "up-to-date" }
  | { step: "failed"; reason: UpdateFailure };

export type UpdateFailure = "network" | "signature" | "unavailable" | "failed";

/** 0 to 100, or `null` when the server didn't say how big the download is. */
export function progressPercent(downloaded: number, total: number | null): number | null {
  if (!total || total <= 0) return null;
  return Math.min(100, Math.max(0, Math.floor((downloaded / total) * 100)));
}

export function applyProgress(progress: UpdateProgress): UpdateState {
  return progress.event === "installing"
    ? { step: "installing" }
    : { step: "downloading", downloaded: progress.downloaded, total: progress.total };
}

/** Why an update failed, in the words the screen has messages for. */
export function failureReason(error: unknown): UpdateFailure {
  if (!isCommandError(error)) return "failed";
  switch (error.code) {
    case "network":
      return "network";
    case "update-signature-invalid":
      return "signature";
    case "update-unavailable":
      return "unavailable";
    default:
      return "failed";
  }
}
