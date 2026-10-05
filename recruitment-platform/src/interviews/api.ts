import type { components } from "@hirevion/api-client";
import { apiClient } from "@/data/api";

/** Interview templates (PRD §21, §80) and the organisation's interview defaults. */

type Schemas = components["schemas"];
export type Template = Schemas["TemplateResponse"];
export type TemplateSummary = Schemas["TemplateSummary"];
export type TemplateVersion = Schemas["TemplateVersionResponse"];
export type TemplateBody = Schemas["TemplateBody"];
export type TemplateCreate = Schemas["TemplateCreate"];
export type MatrixRow = Schemas["MatrixRowResponse"];
export type MatrixPreview = Schemas["MatrixPreview"];
export type InterviewDefaults = Schemas["InterviewDefaults"];
export type InterviewDefaultsUpdate = Schemas["InterviewDefaultsUpdate"];
export type ProctoringLevel = Template["proctoring_level"];
export type ThirdEye = Template["third_eye"];

export const PROCTORING_LEVELS = [
  "off",
  "basic",
  "standard",
  "strict",
] as const satisfies readonly ProctoringLevel[];
export const THIRD_EYE_MODES = [
  "off",
  "optional",
  "required",
] as const satisfies readonly ThirdEye[];
// PRD §44's evaluation dimensions, in the API's order.
export const RUBRIC_DIMENSIONS = [
  "relevance",
  "correctness",
  "completeness",
  "technical_depth",
  "reasoning",
  "clarity",
  "communication",
  "evidence",
] as const;

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

function required<T>(data: T | undefined): T {
  if (data === undefined) throw new Error("The API answered without a body");
  return data;
}

const one = (id: string) => ({ path: { template_id: id } });

export async function listTemplates(
  query: {
    status?: "active" | "archived" | undefined;
    q?: string | undefined;
    limit?: number;
    cursor?: string | null | undefined;
  } = {},
): Promise<Page<TemplateSummary>> {
  const cleaned = Object.fromEntries(
    Object.entries(query).filter(
      ([, value]) => value !== undefined && value !== null && value !== "",
    ),
  );
  return required(
    (await apiClient().GET("/api/v1/interview-templates", { params: { query: cleaned } })).data,
  );
}

export async function createTemplate(body: TemplateCreate, key: string): Promise<Template> {
  return required(
    (
      await apiClient().POST("/api/v1/interview-templates", {
        body,
        params: { header: { "Idempotency-Key": key } },
      })
    ).data,
  );
}

export async function getTemplate(id: string): Promise<Template> {
  return required(
    (await apiClient().GET("/api/v1/interview-templates/{template_id}", { params: one(id) })).data,
  );
}

/** Saves the fields sent as the template's next version. */
export async function updateTemplate(id: string, body: TemplateBody): Promise<Template> {
  return required(
    (
      await apiClient().PATCH("/api/v1/interview-templates/{template_id}", {
        params: one(id),
        body,
      })
    ).data,
  );
}

export async function listTemplateVersions(id: string): Promise<TemplateVersion[]> {
  return required(
    (
      await apiClient().GET("/api/v1/interview-templates/{template_id}/versions", {
        params: one(id),
      })
    ).data,
  );
}

export async function getSkillMatrix(id: string): Promise<MatrixRow[]> {
  return required(
    (
      await apiClient().GET("/api/v1/interview-templates/{template_id}/skill-matrix", {
        params: one(id),
      })
    ).data,
  );
}

/** The skill matrix for settings that aren't saved yet. */
export async function previewSkillMatrix(body: MatrixPreview): Promise<MatrixRow[]> {
  return required(
    (await apiClient().POST("/api/v1/interview-templates/skill-matrix", { body })).data,
  );
}

export async function setTemplateArchived(id: string, archived: boolean): Promise<Template> {
  const path = archived
    ? "/api/v1/interview-templates/{template_id}/archive"
    : "/api/v1/interview-templates/{template_id}/restore";
  return required((await apiClient().POST(path, { params: one(id) })).data);
}

export async function getInterviewDefaults(): Promise<InterviewDefaults> {
  return required((await apiClient().GET("/api/v1/interview-defaults")).data);
}

export async function saveInterviewDefaults(
  body: InterviewDefaultsUpdate,
): Promise<InterviewDefaults> {
  return required((await apiClient().PUT("/api/v1/interview-defaults", { body })).data);
}
