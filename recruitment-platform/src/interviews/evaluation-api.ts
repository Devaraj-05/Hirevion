import type { components } from "@hirevion/api-client";
import { apiClient } from "@/data/api";

/** The evaluation of an interview (SP-10): its scores with their verified evidence, the
 * reviewers' own scores, and the organisation's agreement with the AI. */

type Schemas = components["schemas"];
export type EvaluationResponse = Schemas["EvaluationResponse"];
export type EvaluationBody = Schemas["EvaluationBody"];
export type QuestionEvaluation = Schemas["QuestionEvaluationDetail"];
export type QuestionEvaluationBrief = Schemas["QuestionEvaluationBrief"];
export type EvaluationEvidence = Schemas["EvaluationEvidence"];
export type HumanScore = Schemas["HumanScoreResponse"];
export type Calibration = Schemas["CalibrationResponse"];
export type RerunQueued = Schemas["RerunQueued"];

function required<T>(data: T | undefined): T {
  if (data === undefined) throw new Error("The API answered without a body");
  return data;
}

const one = (id: string) => ({ path: { interview_id: id } });

export async function getEvaluation(id: string): Promise<EvaluationResponse> {
  return required(
    (await apiClient().GET("/api/v1/interviews/{interview_id}/evaluation", { params: one(id) }))
      .data,
  );
}

export async function getQuestionEvaluation(
  id: string,
  questionId: string,
): Promise<QuestionEvaluation> {
  return required(
    (
      await apiClient().GET(
        "/api/v1/interviews/{interview_id}/evaluation/questions/{question_id}",
        { params: { path: { interview_id: id, question_id: questionId } } },
      )
    ).data,
  );
}

export async function listMyScores(id: string): Promise<HumanScore[]> {
  return required(
    (await apiClient().GET("/api/v1/interviews/{interview_id}/human-scores", { params: one(id) }))
      .data,
  );
}

export async function saveMyScores(
  id: string,
  questionId: string,
  dimensions: Record<string, number>,
  note: string,
): Promise<HumanScore> {
  return required(
    (
      await apiClient().PUT(
        "/api/v1/interviews/{interview_id}/questions/{question_id}/human-scores",
        {
          params: { path: { interview_id: id, question_id: questionId } },
          body: { dimensions, note },
        },
      )
    ).data,
  );
}

export async function getCalibration(): Promise<Calibration> {
  return required((await apiClient().GET("/api/v1/evaluation/calibration")).data);
}

export async function queueRerun(id: string): Promise<RerunQueued> {
  return required(
    (
      await apiClient().POST("/api/v1/interviews/{interview_id}/evaluation/rerun", {
        params: one(id),
      })
    ).data,
  );
}

export const evaluationKeys = {
  detail: (id: string) => ["interviews", "evaluation", id] as const,
  question: (id: string, questionId: string) =>
    ["interviews", "evaluation", id, "question", questionId] as const,
  mine: (id: string) => ["interviews", "human-scores", id] as const,
  calibration: ["evaluation", "calibration"] as const,
};
