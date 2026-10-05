import type { components } from "@hirevion/api-client";
import { apiClient } from "@/data/api";

/** Screening (PRD §15–18): configuration, results, actions and export. */

type Schemas = components["schemas"];
export type ScreeningConfig = Schemas["ScreeningConfigResponse"];
export type ScreeningConfigUpdate = Schemas["ScreeningConfigUpdate"];
export type ScreeningSummary = Schemas["ScreeningSummary"];
export type RankedApplication = Schemas["RankedApplication"];
export type ApplicationScreening = Schemas["ApplicationScreening"];
export type ScreeningResult = Schemas["ScreeningResultResponse"];
export type Action = Schemas["ActionRequest"]["action"];
export type ApplicationState = Schemas["ApplicationState"];

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

function required<T>(data: T | undefined): T {
  if (data === undefined) throw new Error("The API answered without a body");
  return data;
}

const job = (id: string) => ({ path: { job_id: id } });

export async function getJobScreeningConfig(jobId: string): Promise<ScreeningConfig> {
  return required(
    (await apiClient().GET("/api/v1/jobs/{job_id}/screening-config", { params: job(jobId) })).data,
  );
}

export async function saveJobScreeningConfig(
  jobId: string,
  body: ScreeningConfigUpdate,
): Promise<ScreeningConfig> {
  return required(
    (
      await apiClient().PUT("/api/v1/jobs/{job_id}/screening-config", {
        params: job(jobId),
        body,
      })
    ).data,
  );
}

export async function resetJobScreeningConfig(jobId: string): Promise<ScreeningConfig> {
  return required(
    (await apiClient().DELETE("/api/v1/jobs/{job_id}/screening-config", { params: job(jobId) }))
      .data,
  );
}

export async function getScreeningDefaults(): Promise<ScreeningConfig> {
  return required((await apiClient().GET("/api/v1/screening-config")).data);
}

export async function saveScreeningDefaults(body: ScreeningConfigUpdate): Promise<ScreeningConfig> {
  return required((await apiClient().PUT("/api/v1/screening-config", { body })).data);
}

export async function screenJob(jobId: string, applicationIds?: string[]): Promise<number> {
  const { data } = await apiClient().POST("/api/v1/jobs/{job_id}/screen", {
    params: job(jobId),
    body: applicationIds ? { application_ids: applicationIds } : {},
  });
  return required(data).queued;
}

export async function getScreeningSummary(jobId: string): Promise<ScreeningSummary> {
  return required(
    (await apiClient().GET("/api/v1/jobs/{job_id}/screening-summary", { params: job(jobId) })).data,
  );
}

export async function listScreeningResults(
  jobId: string,
  query: { stage?: string | undefined; cursor?: string | null | undefined; limit?: number } = {},
): Promise<Page<RankedApplication>> {
  const clean = Object.fromEntries(
    Object.entries(query).filter(
      ([, value]) => value !== undefined && value !== null && value !== "",
    ),
  );
  return required(
    (
      await apiClient().GET("/api/v1/jobs/{job_id}/screening-results", {
        params: { path: { job_id: jobId }, query: clean },
      })
    ).data,
  );
}

export async function getApplicationScreening(
  applicationId: string,
): Promise<ApplicationScreening> {
  return required(
    (
      await apiClient().GET("/api/v1/applications/{application_id}/screening", {
        params: { path: { application_id: applicationId } },
      })
    ).data,
  );
}

export async function actOnApplications(
  jobId: string,
  body: {
    application_ids: string[];
    action: Action;
    reason?: string | null;
    user_id?: string | null;
  },
): Promise<ApplicationState[]> {
  return required(
    (
      await apiClient().POST("/api/v1/jobs/{job_id}/applications/actions", {
        params: job(jobId),
        body,
      })
    ).data,
  ).applications;
}

/** The ranking as a file (needs a recent password: wrap the call in `useStepUp`). */
export async function exportRanking(jobId: string, format: "csv" | "xlsx"): Promise<Blob> {
  const { data } = await apiClient().GET("/api/v1/jobs/{job_id}/screening-results/export", {
    params: { path: { job_id: jobId }, query: { format } },
    parseAs: "blob",
  });
  return required(data as Blob | undefined);
}
