import type { components } from "@hirevion/api-client";
import { apiClient } from "@/data/api";

/** Reports (SP-17; PRD §68, §69, §99): a report is a document of blocks the web renders and the
 * server renders to a PDF. Failures are thrown as `ApiProblem`s. */

type Schemas = components["schemas"];
export type ReportDocument = Schemas["ReportDocument"];
export type ReportSection = Schemas["ReportSection"];
export type ReportBlock = ReportSection["blocks"][number];
export type ReportKind = ReportDocument["kind"];
export type ReportExport = Schemas["ReportExportResponse"];
export type CandidateReport = Schemas["CandidateReportResponse"];
export type CandidateReportItem = Schemas["CandidateReportItem"];
export type DraftItem = Schemas["DraftItem"];

export const ITEM_KEYS = [
  "completion",
  "general_feedback",
  "technical_feedback",
  "coding_feedback",
  "next_step",
] as const;
export type ItemKey = (typeof ITEM_KEYS)[number];

function required<T>(data: T | undefined): T {
  if (data === undefined) throw new Error("The API answered without a body");
  return data;
}

const interview = (id: string) => ({ params: { path: { interview_id: id } } });

export async function getInterviewReport(id: string): Promise<ReportDocument> {
  return required(
    (await apiClient().GET("/api/v1/interviews/{interview_id}/reports/interview", interview(id)))
      .data,
  );
}

export async function getProctoringReport(id: string): Promise<ReportDocument> {
  return required(
    (await apiClient().GET("/api/v1/interviews/{interview_id}/reports/proctoring", interview(id)))
      .data,
  );
}

export async function getCodingReport(id: string): Promise<ReportDocument> {
  return required(
    (await apiClient().GET("/api/v1/interviews/{interview_id}/reports/coding", interview(id))).data,
  );
}

export async function getCandidateReport(candidateId: string): Promise<ReportDocument> {
  return required(
    (
      await apiClient().GET("/api/v1/candidates/{candidate_id}/report", {
        params: { path: { candidate_id: candidateId } },
      })
    ).data,
  );
}

export async function createExport(body: {
  kind: ReportKind;
  interview_id?: string;
  candidate_id?: string;
}): Promise<ReportExport> {
  return required((await apiClient().POST("/api/v1/report-exports", { body })).data);
}

export async function listExports(subject: {
  interviewId?: string;
  candidateId?: string;
}): Promise<ReportExport[]> {
  const query: { interview_id?: string; candidate_id?: string } = {};
  if (subject.interviewId) query.interview_id = subject.interviewId;
  if (subject.candidateId) query.candidate_id = subject.candidateId;
  return required((await apiClient().GET("/api/v1/report-exports", { params: { query } })).data)
    .items;
}

/** The PDF itself is fetched by the browser (a link), so the download is an audited GET. */
export function downloadHref(exportId: string): string {
  return `/api/v1/report-exports/${exportId}/download`;
}

export async function getCandidateReportState(id: string): Promise<CandidateReport> {
  return required(
    (await apiClient().GET("/api/v1/interviews/{interview_id}/candidate-report", interview(id)))
      .data,
  );
}

export async function saveCandidateReport(
  id: string,
  items: Record<string, DraftItem>,
): Promise<CandidateReport> {
  return required(
    (
      await apiClient().PUT("/api/v1/interviews/{interview_id}/candidate-report", {
        ...interview(id),
        body: { items },
      })
    ).data,
  );
}

export async function approveCandidateReport(id: string): Promise<CandidateReport> {
  return required(
    (
      await apiClient().POST(
        "/api/v1/interviews/{interview_id}/candidate-report/approve",
        interview(id),
      )
    ).data,
  );
}

export async function withdrawCandidateReport(
  id: string,
  reason: string,
): Promise<CandidateReport> {
  return required(
    (
      await apiClient().POST("/api/v1/interviews/{interview_id}/candidate-report/withdraw", {
        ...interview(id),
        body: { reason },
      })
    ).data,
  );
}

export async function getReportSettings(): Promise<Record<string, boolean>> {
  return required((await apiClient().GET("/api/v1/organization/candidate-report")).data).items;
}

export async function saveReportSettings(
  items: Record<string, boolean>,
): Promise<Record<string, boolean>> {
  return required(
    (await apiClient().PUT("/api/v1/organization/candidate-report", { body: { items } })).data,
  ).items;
}

export const reportKeys = {
  interview: (id: string) => ["reports", "interview", id] as const,
  proctoring: (id: string) => ["reports", "proctoring", id] as const,
  coding: (id: string) => ["reports", "coding", id] as const,
  candidate: (id: string) => ["reports", "candidate", id] as const,
  exports: (subject: string) => ["reports", "exports", subject] as const,
  candidateReport: (id: string) => ["reports", "candidate-report", id] as const,
  settings: ["reports", "settings"] as const,
};
