import type { components } from "@hirevion/api-client";
import { apiClient } from "@/data/api";

/**
 * Resumes and candidates (PRD §13, §19). Failures are thrown as `ApiProblem`s; an upload takes
 * an `Idempotency-Key` made once per file and reused if that file is sent again.
 */

type Schemas = components["schemas"];
export type ResumeDocument = Schemas["ResumeDocumentResponse"];
export type CandidateSummary = Schemas["CandidateSummary"];
export type Candidate = Schemas["CandidateResponse"];
export type Application = Schemas["ApplicationResponse"];
export type Stage = Application["stage"];

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

function required<T>(data: T | undefined): T {
  if (data === undefined) throw new Error("The API answered without a body");
  return data;
}

type Defined<T> = { [K in keyof T]?: Exclude<T[K], undefined> };

function cleanQuery<T extends object>(query: T): Defined<T> {
  return Object.fromEntries(
    Object.entries(query).filter(
      ([, value]) => value !== undefined && value !== null && value !== "",
    ),
  ) as Defined<T>;
}

interface Paging {
  limit?: number | undefined;
  cursor?: string | null | undefined;
}

export async function uploadResume(
  jobId: string,
  file: File,
  key: string,
): Promise<ResumeDocument> {
  const form = new FormData();
  form.append("file", file);
  return required(
    (
      await apiClient().POST("/api/v1/jobs/{job_id}/resumes", {
        params: { path: { job_id: jobId }, header: { "Idempotency-Key": key } },
        body: { file: "" },
        bodySerializer: () => form,
      })
    ).data,
  );
}

export async function listResumes(
  jobId: string,
  query: Paging & { parent_id?: string | undefined } = {},
): Promise<Page<ResumeDocument>> {
  return required(
    (
      await apiClient().GET("/api/v1/jobs/{job_id}/resumes", {
        params: { path: { job_id: jobId }, query: cleanQuery(query) },
      })
    ).data,
  );
}

export async function listApplications(
  jobId: string,
  query: Paging = {},
): Promise<Page<Application>> {
  return required(
    (
      await apiClient().GET("/api/v1/jobs/{job_id}/applications", {
        params: { path: { job_id: jobId }, query: cleanQuery(query) },
      })
    ).data,
  );
}

export async function listCandidates(
  query: Paging & { q?: string | undefined; job_id?: string | undefined } = {},
): Promise<Page<CandidateSummary>> {
  return required(
    (await apiClient().GET("/api/v1/candidates", { params: { query: cleanQuery(query) } })).data,
  );
}

export async function getCandidate(id: string): Promise<Candidate> {
  return required(
    (
      await apiClient().GET("/api/v1/candidates/{candidate_id}", {
        params: { path: { candidate_id: id } },
      })
    ).data,
  );
}

/** Same-origin: the API answers with a short-lived link to the file, and audits it. */
export function downloadHref(documentId: string): string {
  return `/api/v1/documents/${documentId}/download`;
}
