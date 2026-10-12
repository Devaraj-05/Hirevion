import type { UpdateOutcome, UpdateProgress } from "../native/commands";
import { isCommandError } from "../native/commands";

/**
 * The update screen's state: nothing started, a check, download or install running, or one of
 * three ends: nothing newer, installed (restart the app), or a failure.
 */
export type UpdateState =
  | { step: "idle" }
  | { step: "checking" }
  | { step: "downloading"; downloaded: number; total: number | null }
  | { step: "installing" }
  | { step: "up-to-date" }
  | { step: "restart" }
  | { step: "failed"; reason: UpdateFailure };

export type UpdateFailure = "network" | "server" | "signature" | "unavailable" | "failed";

/** Whether the update is running, so the button stays disabled. */
export function isBusy(state: UpdateState): boolean {
  return state.step === "checking" || state.step === "downloading" || state.step === "installing";
}

/** 0 to 100, or `null` when the server didn't say how big the download is. */
export function progressPercent(downloaded: number, total: number | null): number | null {
  if (!total || total <= 0) return null;
  return Math.min(100, Math.max(0, Math.floor((downloaded / total) * 100)));
}

/**
 * What a progress message does to the screen. Messages arrive on a channel of their own, so one
 * can land after the command has already answered (a failure, "nothing newer", the restart
 * prompt): those are ignored, or a late "installing" would hide the error behind a disabled button.
 */
export function applyProgress(state: UpdateState, progress: UpdateProgress): UpdateState {
  if (state.step !== "checking" && state.step !== "downloading") return state;
  return progress.event === "installing"
    ? { step: "installing" }
    : { step: "downloading", downloaded: progress.downloaded, total: progress.total };
}

/** The end state for a command that answered. `installed` is reached only where the installer
 * returns to the app (on Windows it ends the app and starts the new version itself). */
export function outcomeState(status: UpdateOutcome["status"]): UpdateState {
  return status === "installed" ? { step: "restart" } : { step: "up-to-date" };
}

/** Why an update failed, in the words the screen has messages for. */
export function failureReason(error: unknown): UpdateFailure {
  if (!isCommandError(error)) return "failed";
  switch (error.code) {
    case "network":
      return "network";
    case "update-server-error":
      return "server";
    case "update-signature-invalid":
      return "signature";
    case "update-unavailable":
      return "unavailable";
    default:
      return "failed";
  }
}
