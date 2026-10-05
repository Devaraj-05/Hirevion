import type { components } from "@hirevion/api-client";
import { apiClient } from "@/data/api";

/** The question library (PRD §22–23): questions with versions, approval and AI drafts. */

type Schemas = components["schemas"];
export type Question = Schemas["QuestionResponse"];
export type QuestionBody = Schemas["QuestionBody"];
export type QuestionCreate = Schemas["QuestionCreate"];
export type QuestionVersion = Schemas["QuestionVersionResponse"];
export type GenerateRequest = Schemas["GenerateRequest"];
export type GenerateResult = Schemas["GenerateResponse"];
export type QuestionType = Question["type"];
export type Category = Question["category"];
export type Difficulty = Question["difficulty"];
export type QuestionStatus = Question["status"];

export const QUESTION_TYPES = [
  "technical",
  "conceptual",
  "scenario",
  "problem_solving",
  "system_design",
  "coding",
  "resume_based",
  "project_based",
] as const satisfies readonly QuestionType[];
export const CATEGORIES = [
  "technical",
  "coding",
  "system_design",
  "resume_based",
  "custom",
] as const satisfies readonly Category[];
export const DIFFICULTIES = ["easy", "medium", "hard"] as const satisfies readonly Difficulty[];
export const LEVELS = ["junior", "mid", "senior", "lead"] as const;
export const CODING_LANGUAGES = ["python", "javascript", "typescript", "sql"] as const;
export type CodingLanguage = (typeof CODING_LANGUAGES)[number];

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

export interface QuestionQuery {
  category?: Category | undefined;
  type?: QuestionType | undefined;
  difficulty?: Difficulty | undefined;
  status?: QuestionStatus | undefined;
  skill?: string | undefined;
  q?: string | undefined;
  limit?: number | undefined;
  cursor?: string | null | undefined;
}

function required<T>(data: T | undefined): T {
  if (data === undefined) throw new Error("The API answered without a body");
  return data;
}

type Defined<T> = { [K in keyof T]?: Exclude<T[K], undefined> };

function clean<T extends object>(query: T): Defined<T> {
  return Object.fromEntries(
    Object.entries(query).filter(
      ([, value]) => value !== undefined && value !== null && value !== "",
    ),
  ) as Defined<T>;
}

const one = (id: string) => ({ path: { question_id: id } });

export async function listQuestions(query: QuestionQuery = {}): Promise<Page<Question>> {
  return required(
    (await apiClient().GET("/api/v1/questions", { params: { query: clean(query) } })).data,
  );
}

export async function createQuestion(body: QuestionCreate, key: string): Promise<Question> {
  return required(
    (
      await apiClient().POST("/api/v1/questions", {
        body,
        params: { header: { "Idempotency-Key": key } },
      })
    ).data,
  );
}

export async function getQuestion(id: string): Promise<Question> {
  return required(
    (await apiClient().GET("/api/v1/questions/{question_id}", { params: one(id) })).data,
  );
}

/** Saves the question as its next version. */
export async function updateQuestion(id: string, body: QuestionBody): Promise<Question> {
  return required(
    (await apiClient().PUT("/api/v1/questions/{question_id}", { params: one(id), body })).data,
  );
}

export async function listQuestionVersions(id: string): Promise<QuestionVersion[]> {
  return required(
    (await apiClient().GET("/api/v1/questions/{question_id}/versions", { params: one(id) })).data,
  );
}

export async function approveQuestion(id: string): Promise<Question> {
  return required(
    (await apiClient().POST("/api/v1/questions/{question_id}/approve", { params: one(id) })).data,
  );
}

export async function archiveQuestion(id: string): Promise<Question> {
  return required(
    (await apiClient().POST("/api/v1/questions/{question_id}/archive", { params: one(id) })).data,
  );
}

export async function restoreQuestion(id: string): Promise<Question> {
  return required(
    (await apiClient().POST("/api/v1/questions/{question_id}/restore", { params: one(id) })).data,
  );
}

/** Drafts questions with AI; a recruiter approves each before it can be used. */
export async function generateQuestions(body: GenerateRequest): Promise<GenerateResult> {
  return required((await apiClient().POST("/api/v1/questions/generate", { body })).data);
}
