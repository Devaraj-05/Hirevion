import type { components } from "@hirevion/api-client";
import { apiClient } from "@/data/api";

/** Candidates' requests from the portal, for recruiters (SP-07b; ADR-0022). */

export type CandidateRequest = components["schemas"]["CandidateRequestItem"];
export type RequestStatus = CandidateRequest["status"];
export type RequestUpdate = components["schemas"]["CandidateRequestUpdate"];

export const REQUEST_STATUSES = ["open", "in_progress", "resolved", "declined"] as const;

export const requestKeys = {
  all: ["candidate-requests"] as const,
  list: (status: RequestStatus | null) => ["candidate-requests", status ?? "all"] as const,
};

export async function listCandidateRequests(
  status: RequestStatus | null,
  cursor: string | null,
): Promise<{ items: CandidateRequest[]; next_cursor: string | null }> {
  const { data } = await apiClient().GET("/api/v1/candidate-requests", {
    params: {
      query: { limit: 50, ...(status ? { status } : {}), ...(cursor ? { cursor } : {}) },
    },
  });
  if (!data) throw new Error("The API answered without a body");
  return data;
}

export async function updateCandidateRequest(
  id: string,
  body: RequestUpdate,
): Promise<CandidateRequest> {
  const { data } = await apiClient().PATCH("/api/v1/candidate-requests/{request_id}", {
    params: { path: { request_id: id } },
    body,
  });
  if (!data) throw new Error("The API answered without a body");
  return data;
}
