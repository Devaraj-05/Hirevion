import type { UploadProgress } from "../native/commands";

/** How often the upload-drain screen asks Rust how far the upload is. */
export const UPLOAD_POLL_MS = 2_000;

/** What the screen shows (PRD §51: never "safe to close" before every segment is settled). */
export type UploadView =
  | { state: "checking" }
  | { state: "uploading"; percent: number; pending: number }
  /** `gaps` are parts the server will never get (lost or refused): the screen says so. */
  | { state: "done"; gaps: number };

export function uploadView(progress: UploadProgress | null): UploadView {
  if (!progress) return { state: "checking" };
  // Trust nothing but Rust's own "done", and double-check it against what it counted.
  if (progress.done && !progress.recording && progress.pending === 0) {
    return { state: "done", gaps: progress.lost + progress.rejected };
  }
  const percent = Math.min(99, Math.max(0, Math.floor(progress.percent)));
  return { state: "uploading", percent, pending: progress.pending };
}
