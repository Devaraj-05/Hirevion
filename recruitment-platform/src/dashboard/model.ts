/** The dashboard's vocabulary: PRD §10 figures and filters, §72 hiring statuses, §24 interview states. */

export const KPIS = [
  "openJobs",
  "activeCandidates",
  "screened",
  "shortlisted",
  "interviewsScheduled",
  "liveInterviews",
  "completedInterviews",
  "pendingReviews",
  "proctoringAlerts",
  "inPipeline",
] as const;
export type Kpi = (typeof KPIS)[number];

export const PIPELINE_STATUSES = [
  "under_review",
  "shortlisted",
  "interview_invited",
  "interview_started",
  "interview_completed",
  "additional_review",
  "selected",
  "rejected",
  "on_hold",
] as const;
export type PipelineStatus = (typeof PIPELINE_STATUSES)[number];

export const INTERVIEW_STATUSES = [
  "scheduled",
  "invited",
  "in_progress",
  "interrupted",
  "completed",
  "evaluating",
  "evaluated",
  "expired",
  "cancelled",
  "abandoned",
] as const;

/** URL parameters: the date range, then the five PRD §10 selections. */
export const DASHBOARD_FILTERS = [
  "from",
  "to",
  "recruiter",
  "team",
  "job",
  "department",
  "candidateStatus",
  "interviewStatus",
] as const;

/** Filters whose choices come from the organisation's data (SP-02, SP-04). */
export type DataFilter = "recruiter" | "team" | "job" | "department";

export interface PipelineCard {
  id: string;
  name: string;
  job: string;
}
