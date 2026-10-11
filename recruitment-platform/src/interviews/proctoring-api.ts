import type { components } from "@hirevion/api-client";
import { apiClient } from "@/data/api";

/** The live monitoring of an interview (SP-14; PRD §65, §66): a snapshot to start from, then
 * the proctoring websocket; and the recruiter's review of an event. */

type Schemas = components["schemas"];
export type LiveSnapshot = Schemas["LiveSnapshot"];
export type ProctorEvent = Schemas["ProctorEventItem"];
export type ProctoringStatus = Schemas["ProctoringStatus"];
export type Counts = Schemas["Counts"];
export type ReviewOutcome = Schemas["ReviewBody"]["outcome"];

function required<T>(data: T | undefined): T {
  if (data === undefined) throw new Error("The API answered without a body");
  return data;
}

export async function getLiveSnapshot(id: string): Promise<LiveSnapshot> {
  return required(
    (
      await apiClient().GET("/api/v1/proctoring/{interview_id}/live", {
        params: { path: { interview_id: id } },
      })
    ).data,
  );
}

export async function reviewEvent(
  id: string,
  eventId: string,
  outcome: ReviewOutcome,
  reason: string,
): Promise<ProctorEvent> {
  return required(
    (
      await apiClient().POST("/api/v1/proctoring/{interview_id}/events/{event_id}/review", {
        params: { path: { interview_id: id, event_id: eventId } },
        body: { outcome, reason },
      })
    ).data,
  );
}

/** The websocket of the live dashboard, replaying from the last event id seen. */
export function proctoringSocketUrl(id: string, after?: string | null): string {
  const origin = window.location.origin.replace(/^http/, "ws");
  const query = after ? `?after=${encodeURIComponent(after)}` : "";
  return `${origin}/api/v1/ws/proctoring/${encodeURIComponent(id)}${query}`;
}

export const proctoringKeys = {
  live: (id: string) => ["interviews", "proctoring-live", id] as const,
};
