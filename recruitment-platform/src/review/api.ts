import type { components } from "@hirevion/api-client";
import { apiClient } from "@/data/api";

/** The review workspace, the hiring workflow and Candidate 360 (SP-17; PRD §20, §71, §72, §98).
 * Failures are thrown as `ApiProblem`s. */

type Schemas = components["schemas"];
export type ReviewMedia = Schemas["ReviewMediaResponse"];
export type MediaTrack = Schemas["MediaTrackResponse"];
export type Note = Schemas["NoteResponse"];
export type Scores = Schemas["ScoresResponse"];
export type ScoreValue = Schemas["ScoreValueResponse"];
export type ScoreScope = Schemas["ScoreChangeBody"]["scope"];
export type HiringState = Schemas["HiringStateResponse"];
export type HiringStatus = HiringState["status"];
export type HistoryItem = Schemas["HistoryItem"];
export type HiringInput = Schemas["HiringInputResponse"];
export type Recommendation = Schemas["HiringInputBody"]["recommendation"];
export type PendingReviews = Schemas["PendingReviewList"];
export type Pipeline = Schemas["PipelineResponse"];
export type PipelineCard = Schemas["PipelineCard"];
export type Candidate360 = Schemas["Candidate360Response"];
export type InterviewHistoryItem = Schemas["InterviewHistoryItem"];
export type Timeline = Schemas["TimelineResponse"];
export type TimelineItem = Schemas["TimelineItem"];
export type TimelineSource = TimelineItem["source"];

/** PRD §72's nine statuses, in the order the pipeline shows them. */
export const HIRING_STATUSES = [
  "under_review",
  "shortlisted",
  "interview_invited",
  "interview_started",
  "interview_completed",
  "additional_review",
  "selected",
  "rejected",
  "on_hold",
] as const satisfies readonly HiringStatus[];

/** Statuses that need a reason when a person chooses them. */
export const REASON_REQUIRED: readonly HiringStatus[] = [
  "additional_review",
  "on_hold",
  "selected",
  "rejected",
];

/** PRD §98's eight sources. */
export const TIMELINE_SOURCES = [
  "screening",
  "interview",
  "transcript",
  "coding",
  "proctoring",
  "recording",
  "evaluation",
  "recruiter",
] as const satisfies readonly TimelineSource[];

export const RECOMMENDATIONS = [
  "strong_hire",
  "hire",
  "hold",
  "no_hire",
  "strong_no_hire",
] as const satisfies readonly Recommendation[];

function required<T>(data: T | undefined): T {
  if (data === undefined) throw new Error("The API answered without a body");
  return data;
}

const interview = (id: string) => ({ params: { path: { interview_id: id } } });
const application = (id: string) => ({ params: { path: { application_id: id } } });
const candidate = (id: string) => ({ params: { path: { candidate_id: id } } });

export async function getReviewMedia(id: string): Promise<ReviewMedia> {
  return required(
    (await apiClient().GET("/api/v1/interviews/{interview_id}/review/media", interview(id))).data,
  );
}

export async function listInterviewNotes(id: string): Promise<Note[]> {
  return required(
    (await apiClient().GET("/api/v1/interviews/{interview_id}/notes", interview(id))).data,
  ).items;
}

export async function addInterviewNote(
  id: string,
  body: { body: string; at_ms?: number | null },
): Promise<Note> {
  return required(
    (await apiClient().POST("/api/v1/interviews/{interview_id}/notes", { ...interview(id), body }))
      .data,
  );
}

export async function listCandidateNotes(id: string): Promise<Note[]> {
  return required(
    (await apiClient().GET("/api/v1/candidates/{candidate_id}/notes", candidate(id))).data,
  ).items;
}

export async function addCandidateNote(id: string, body: string): Promise<Note> {
  return required(
    (
      await apiClient().POST("/api/v1/candidates/{candidate_id}/notes", {
        ...candidate(id),
        body: { body },
      })
    ).data,
  );
}

export async function getScores(id: string): Promise<Scores> {
  return required(
    (await apiClient().GET("/api/v1/interviews/{interview_id}/scores", interview(id))).data,
  );
}

export async function changeScore(
  id: string,
  body: { scope: ScoreScope; target: string | null; new_score: number; reason: string },
): Promise<Scores> {
  return required(
    (
      await apiClient().POST("/api/v1/interviews/{interview_id}/score-changes", {
        ...interview(id),
        body,
      })
    ).data,
  );
}

export async function getHiringState(applicationId: string): Promise<HiringState> {
  return required(
    (
      await apiClient().GET(
        "/api/v1/applications/{application_id}/hiring",
        application(applicationId),
      )
    ).data,
  );
}

export async function changeHiringStatus(
  applicationId: string,
  body: { status: HiringStatus; reason: string | null },
): Promise<HiringState> {
  return required(
    (
      await apiClient().POST("/api/v1/applications/{application_id}/hiring-status", {
        ...application(applicationId),
        body,
      })
    ).data,
  );
}

export async function addHiringInput(
  applicationId: string,
  body: { recommendation: Recommendation; ratings: Record<string, number>; rationale: string },
): Promise<HiringInput> {
  return required(
    (
      await apiClient().POST("/api/v1/applications/{application_id}/hiring-inputs", {
        ...application(applicationId),
        body,
      })
    ).data,
  );
}

export async function getPendingReviews(): Promise<PendingReviews> {
  return required((await apiClient().GET("/api/v1/reviews/pending")).data);
}

export async function getPipeline(job?: string): Promise<Pipeline> {
  return required(
    (await apiClient().GET("/api/v1/pipeline", { params: { query: job ? { job } : {} } })).data,
  );
}

export async function getCandidate360(id: string): Promise<Candidate360> {
  return required(
    (await apiClient().GET("/api/v1/candidates/{candidate_id}/360", candidate(id))).data,
  );
}

export async function getTimeline(
  id: string,
  query: { source?: TimelineSource[]; interview_id?: string; before?: string; limit?: number } = {},
): Promise<Timeline> {
  return required(
    (
      await apiClient().GET("/api/v1/candidates/{candidate_id}/timeline", {
        params: { path: { candidate_id: id }, query },
      })
    ).data,
  );
}

export type ProctoringEvents = Schemas["ProctoringReport"];

/** The first hundred proctoring events with their review outcomes (the whole report is
 * `getProctoringReport`). */
export async function getProctoringEvents(id: string): Promise<ProctoringEvents> {
  return required(
    (
      await apiClient().GET("/api/v1/proctoring/{interview_id}", {
        params: { path: { interview_id: id }, query: { limit: 100 } },
      })
    ).data,
  );
}

export const reviewKeys = {
  events: (id: string) => ["review", "events", id] as const,
  media: (id: string) => ["review", "media", id] as const,
  notes: (id: string) => ["review", "notes", id] as const,
  candidateNotes: (id: string) => ["review", "candidate-notes", id] as const,
  scores: (id: string) => ["review", "scores", id] as const,
  hiring: (applicationId: string) => ["review", "hiring", applicationId] as const,
  pending: ["review", "pending"] as const,
  pipeline: (job?: string) => ["review", "pipeline", job ?? ""] as const,
  candidate360: (id: string) => ["review", "360", id] as const,
  timeline: (id: string, source: string) => ["review", "timeline", id, source] as const,
};
