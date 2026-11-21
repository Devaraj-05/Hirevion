import type { components } from "@hirevion/api-client";
import { apiClient } from "@/data/api";

/** One interview's analytics for the recruiter's dashboard (C8-7, ADR-0047). */

type Schemas = components["schemas"];
export type InterviewAnalytics = Schemas["InterviewAnalytics"];
export type AnalyticsQuestion = Schemas["AnalyticsQuestion"];
export type AnalyticsSkill = Schemas["AnalyticsSkill"];
export type AnalyticsEvent = Schemas["AnalyticsEvent"];
export type AnalyticsInventory = Schemas["AnalyticsInventory"];

export const analyticsKeys = {
  detail: (id: string) => ["interviews", "analytics", id] as const,
};

export async function getInterviewAnalytics(id: string): Promise<InterviewAnalytics> {
  const { data } = await apiClient().GET("/api/v1/interviews/{interview_id}/analytics", {
    params: { path: { interview_id: id } },
  });
  if (data === undefined) throw new Error("The API answered without a body");
  return data;
}
