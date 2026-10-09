import type { components } from "@hirevion/api-client";
import type { BadgeTone } from "@hirevion/ui";
import { apiClient } from "@/data/api";
import type { Page } from "./api";

/** Interviews (PRD §24, §25): assignment, the list and detail, invitations and changes. */

type Schemas = components["schemas"];
export type Interview = Schemas["InterviewResponse"];
export type InterviewSummary = Schemas["InterviewSummary"];
export type InterviewStatus = Interview["status"];
export type InterviewEvent = Schemas["InterviewEventResponse"];
export type BulkResult = Schemas["BulkInterviewResult"];
export type DashboardSummary = Schemas["DashboardSummary"];
export type StatusGroup = "upcoming" | "live" | "completed";

export const STATUS_TONES: Record<InterviewStatus, BadgeTone> = {
  scheduled: "neutral",
  invited: "info",
  in_progress: "accent",
  interrupted: "warning",
  completed: "success",
  evaluating: "accent",
  evaluated: "success",
  expired: "warning",
  cancelled: "neutral",
  abandoned: "danger",
};

/** What a recruiter may still do with an interview in each status. */
export function interviewActions(status: InterviewStatus) {
  return {
    invite: status === "scheduled" || status === "invited",
    reschedule: status === "scheduled" || status === "invited" || status === "expired",
    cancel: status === "scheduled" || status === "invited",
  };
}

function required<T>(data: T | undefined): T {
  if (data === undefined) throw new Error("The API answered without a body");
  return data;
}

const one = (id: string) => ({ path: { interview_id: id } });

export async function listInterviews(
  query: {
    status_group?: StatusGroup | undefined;
    q?: string | undefined;
    job_id?: string | undefined;
    candidate_id?: string | undefined;
    limit?: number;
    cursor?: string | null | undefined;
  } = {},
): Promise<Page<InterviewSummary>> {
  const cleaned = Object.fromEntries(
    Object.entries(query).filter(
      ([, value]) => value !== undefined && value !== null && value !== "",
    ),
  );
  return required(
    (await apiClient().GET("/api/v1/interviews", { params: { query: cleaned } })).data,
  );
}

export async function getInterview(id: string): Promise<Interview> {
  return required(
    (await apiClient().GET("/api/v1/interviews/{interview_id}", { params: one(id) })).data,
  );
}

export interface AssignInput {
  application_ids: string[];
  template_id: string | null;
  starts_at: string;
  expires_at: string;
  reviewer_ids?: string[];
  invite: boolean;
}

/** Assigns the same interview to every chosen application; the answer lists what it skipped. */
export async function assignInterviews(input: AssignInput): Promise<BulkResult> {
  return required((await apiClient().POST("/api/v1/interviews/bulk", { body: input })).data);
}

export async function sendInvitation(id: string): Promise<Interview> {
  return required(
    (await apiClient().POST("/api/v1/interviews/{interview_id}/invitation", { params: one(id) }))
      .data,
  );
}

export async function rescheduleInterview(
  id: string,
  body: { starts_at: string; expires_at: string; reason: string | null },
): Promise<Interview> {
  return required(
    (
      await apiClient().POST("/api/v1/interviews/{interview_id}/reschedule", {
        params: one(id),
        body,
      })
    ).data,
  );
}

export async function cancelInterview(id: string, reason: string): Promise<Interview> {
  return required(
    (
      await apiClient().POST("/api/v1/interviews/{interview_id}/cancel", {
        params: one(id),
        body: { reason },
      })
    ).data,
  );
}

export async function setInterviewReviewers(id: string, reviewerIds: string[]): Promise<Interview> {
  return required(
    (
      await apiClient().PUT("/api/v1/interviews/{interview_id}/reviewers", {
        params: one(id),
        body: { reviewer_ids: reviewerIds },
      })
    ).data,
  );
}

export async function getDashboard(
  query: Record<string, string | undefined> = {},
): Promise<DashboardSummary> {
  const cleaned = Object.fromEntries(
    Object.entries(query).filter(([, value]) => value !== undefined && value !== ""),
  );
  return required(
    (await apiClient().GET("/api/v1/dashboard", { params: { query: cleaned } })).data,
  );
}

/** A `datetime-local` input's value as an ISO instant, in the browser's time zone. */
export function localToIso(value: string): string {
  return new Date(value).toISOString();
}

/** An instant as a `datetime-local` value, in the browser's time zone. */
export function isoToLocal(value: string | Date): string {
  const date = typeof value === "string" ? new Date(value) : value;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`;
}

export const interviewKeys = {
  list: ["interviews", "list"] as const,
  detail: (id: string) => ["interviews", "detail", id] as const,
  dashboard: ["dashboard"] as const,
};
