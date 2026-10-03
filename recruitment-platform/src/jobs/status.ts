import type { BadgeTone } from "@hirevion/ui";
import type { JobStatus } from "./api";

/** Where a job may go from each status (PRD §11), as the API enforces it. */
export const TRANSITIONS: Record<JobStatus, readonly JobStatus[]> = {
  draft: ["open"],
  open: ["paused", "closed"],
  paused: ["open", "closed"],
  closed: ["archived"],
  archived: [],
};

export const STATUS_TONES: Record<JobStatus, BadgeTone> = {
  draft: "neutral",
  open: "success",
  paused: "warning",
  closed: "info",
  archived: "neutral",
};

export type StatusAction = "open" | "resume" | "pause" | "close" | "archive";

/** The buttons a job in `status` offers: reopening a paused job reads as "Resume". */
export function statusActions(status: JobStatus): { action: StatusAction; to: JobStatus }[] {
  return TRANSITIONS[status].map((to) => {
    if (to === "open") return { action: status === "paused" ? "resume" : "open", to };
    if (to === "paused") return { action: "pause", to };
    if (to === "closed") return { action: "close", to };
    return { action: "archive", to };
  });
}
