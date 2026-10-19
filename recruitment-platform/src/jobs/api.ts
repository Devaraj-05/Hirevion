import type { components } from "@hirevion/api-client";
import { apiClient } from "@/data/api";

/**
 * The jobs pages' calls (PRD §11–12). Failures are thrown as `ApiProblem`s; creates take an
 * `Idempotency-Key` that a form generates once per submission and reuses when it retries.
 */

type Schemas = components["schemas"];
export type Job = Schemas["JobResponse"];
export type JobSummary = Schemas["JobSummary"];
export type JobFields = Schemas["JobFields"];
export type JobCreate = Schemas["JobCreate"];
export type JobStatus = Job["status"];
export type JobVersion = Schemas["JobVersionResponse"];
export type JobDocument = Schemas["DocumentResponse"];
export type JobDescription = Schemas["JdResponse"];
export type JdApply = Schemas["JdApply"];
export type SkillBody = Schemas["SkillBody"];
export type SkillSuggestion = Schemas["SkillSuggestion"];
export type JobChoices = Schemas["JobChoices"];

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

/** Filters a page leaves out are `undefined`; empty ones are dropped before the request. */
export interface JobQuery {
  status?: JobStatus | undefined;
  department_id?: string | undefined;
  recruiter_id?: string | undefined;
  q?: string | undefined;
  limit?: number | undefined;
  cursor?: string | null | undefined;
}

function required<T>(data: T | undefined): T {
  if (data === undefined) throw new Error("The API answered without a body");
  return data;
}

function idempotent(key: string) {
  return { "Idempotency-Key": key };
}

type Defined<T> = { [K in keyof T]?: Exclude<T[K], undefined> };

function cleanQuery<T extends object>(query: T): Defined<T> {
  return Object.fromEntries(
    Object.entries(query).filter(
      ([, value]) => value !== undefined && value !== null && value !== "",
    ),
  ) as Defined<T>;
}

/** `JOB-0042`, as the API also accepts it in a search. */
export function jobReference(number: number): string {
  return `JOB-${String(number).padStart(4, "0")}`;
}

export async function listJobs(query: JobQuery = {}): Promise<Page<JobSummary>> {
  return required(
    (await apiClient().GET("/api/v1/jobs", { params: { query: cleanQuery(query) } })).data,
  );
}

export async function createJob(body: JobCreate, key: string): Promise<Job> {
  return required(
    (await apiClient().POST("/api/v1/jobs", { body, params: { header: idempotent(key) } })).data,
  );
}

/** The departments, teams and people a job can be assigned to. */
export async function getJobChoices(): Promise<JobChoices> {
  return required((await apiClient().GET("/api/v1/jobs/choices")).data);
}

export async function getJob(id: string): Promise<Job> {
  return required(
    (await apiClient().GET("/api/v1/jobs/{job_id}", { params: { path: { job_id: id } } })).data,
  );
}

export async function updateJob(id: string, changes: JobFields): Promise<Job> {
  return required(
    (
      await apiClient().PATCH("/api/v1/jobs/{job_id}", {
        params: { path: { job_id: id } },
        body: changes,
      })
    ).data,
  );
}

export async function setJobStatus(id: string, status: JobStatus): Promise<Job> {
  return required(
    (
      await apiClient().POST("/api/v1/jobs/{job_id}/status", {
        params: { path: { job_id: id } },
        body: { status },
      })
    ).data,
  );
}

/** The job's history, newest version first, a page at a time. */
export async function listJobVersions(
  id: string,
  query: { cursor?: string | null | undefined; limit?: number } = {},
): Promise<Page<JobVersion>> {
  return required(
    (
      await apiClient().GET("/api/v1/jobs/{job_id}/versions", {
        params: { path: { job_id: id }, query: cleanQuery(query) },
      })
    ).data,
  );
}

/** Sends a description as a file or as pasted text; it's read in the background. */
export async function submitDescription(
  id: string,
  source: { file: File } | { text: string },
  key: string,
): Promise<JobDocument> {
  const form = new FormData();
  if ("file" in source) form.append("file", source.file);
  else form.append("text", source.text);
  return required(
    (
      await apiClient().POST("/api/v1/jobs/{job_id}/jd", {
        params: { path: { job_id: id }, header: idempotent(key) },
        body: {},
        bodySerializer: () => form,
      })
    ).data,
  );
}

/** The job's latest description, or null when it has none yet. */
export async function getDescription(id: string): Promise<JobDescription | null> {
  try {
    return required(
      (
        await apiClient().GET("/api/v1/jobs/{job_id}/jd", {
          params: { path: { job_id: id } },
        })
      ).data,
    );
  } catch (error) {
    if ((error as { code?: string }).code === "no-description") return null;
    throw error;
  }
}

export async function applyDescription(id: string, body: JdApply): Promise<Job> {
  return required(
    (
      await apiClient().POST("/api/v1/jobs/{job_id}/jd/apply", {
        params: { path: { job_id: id } },
        body,
      })
    ).data,
  );
}

export async function retryDocument(id: string): Promise<JobDocument> {
  return required(
    (
      await apiClient().POST("/api/v1/documents/{document_id}/retry", {
        params: { path: { document_id: id } },
      })
    ).data,
  );
}

export async function suggestSkills(q: string): Promise<SkillSuggestion[]> {
  if (!q.trim()) return [];
  const { data } = await apiClient().GET("/api/v1/skills", { params: { query: { q } } });
  return data ?? [];
}
