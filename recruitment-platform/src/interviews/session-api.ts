import type { components } from "@hirevion/api-client";
import { apiClient } from "@/data/api";

/** The interview as it happened (SP-09): its transcript with the questions' sources and the
 * skills' coverage, the candidate's accommodation requests, the organisation's interview
 * briefing, and the live events while it runs. */

type Schemas = components["schemas"];
export type Transcript = Schemas["TranscriptResponse"];
export type TranscriptQuestion = Schemas["TranscriptQuestion"];
export type TranscriptSegment = Schemas["TranscriptSegmentResponse"];
export type Accommodation = Schemas["AccommodationResponse"];
export type InterviewBriefing = Schemas["InterviewBriefingSettings"];

/** What a candidate may ask for (the desktop's accommodation request). */
export const ACCOMMODATION_KINDS = [
  "extended_time",
  "text_answers",
  "breaks",
  "assistive_technology",
  "relaxed_gaze",
  "third_eye_waiver",
] as const;
export type AccommodationKind = (typeof ACCOMMODATION_KINDS)[number];

/** §91's events SP-09 sends; later parts add proctoring, code, recording and third-eye ones. */
export interface LiveEvent {
  id: string;
  type: string;
  interview_id: string;
  at: string;
  data: Record<string, unknown>;
}

function required<T>(data: T | undefined): T {
  if (data === undefined) throw new Error("The API answered without a body");
  return data;
}

const one = (id: string) => ({ path: { interview_id: id } });

export async function getTranscript(id: string): Promise<Transcript> {
  return required(
    (await apiClient().GET("/api/v1/interviews/{interview_id}/transcript", { params: one(id) }))
      .data,
  );
}

export async function listAccommodations(id: string): Promise<Accommodation[]> {
  return required(
    (
      await apiClient().GET("/api/v1/interviews/{interview_id}/accommodations", {
        params: one(id),
      })
    ).data,
  );
}

export async function decideAccommodation(
  id: string,
  accommodationId: string,
  approved: string[],
  note: string | null,
): Promise<Accommodation> {
  return required(
    (
      await apiClient().POST(
        "/api/v1/interviews/{interview_id}/accommodations/{accommodation_id}/decision",
        {
          params: { path: { interview_id: id, accommodation_id: accommodationId } },
          body: { approved, note },
        },
      )
    ).data,
  );
}

export async function getInterviewBriefing(): Promise<InterviewBriefing> {
  return required((await apiClient().GET("/api/v1/organization/interview-briefing")).data);
}

export async function saveInterviewBriefing(body: InterviewBriefing): Promise<InterviewBriefing> {
  return required(
    (await apiClient().PUT("/api/v1/organization/interview-briefing", { body })).data,
  );
}

/** The websocket for an interview's live events, on this app's own origin (the gateway sends
 * /api/* to the backend, so the session cookie goes with it). */
export function liveEventsUrl(id: string, after?: string): string {
  const origin = window.location.origin.replace(/^http/, "ws");
  const query = after ? `?after=${encodeURIComponent(after)}` : "";
  return `${origin}/api/v1/ws/interviews/${encodeURIComponent(id)}${query}`;
}

export const sessionKeys = {
  transcript: (id: string) => ["interviews", "transcript", id] as const,
  accommodations: (id: string) => ["interviews", "accommodations", id] as const,
  briefing: ["organization", "interview-briefing"] as const,
};
