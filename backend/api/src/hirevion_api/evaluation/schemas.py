"""Answers and bodies of the evaluation routes (SP-10; PRD §44, §70, §79)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

EvaluationState = Literal["none", "evaluating", "ready", "failed"]


class EvaluationEvidence(BaseModel):
    """A quote of the candidate's words, checked against the stored transcript."""

    quote: str
    seq: int
    start_ms: int
    end_ms: int
    question_id: UUID | None


class EvaluationDimension(BaseModel):
    dimension: str
    weight: int
    score: float
    """After the cap: a dimension with no verified evidence can't score above 5."""
    raw_score: float
    """As the model gave it."""
    supported: bool
    evidence: list[EvaluationEvidence]
    rationale: str


class QuestionEvaluationBrief(BaseModel):
    question_id: UUID
    position: int
    kind: str
    skill: str | None
    text: str
    weight: float
    overall_score: float
    scores: dict[str, float]
    unsupported: list[str]
    flags: list[str]


class QuestionEvaluationDetail(QuestionEvaluationBrief):
    dimensions: list[EvaluationDimension]
    missing_concepts: list[str]
    note: str
    model: str


class SkillEvaluation(BaseModel):
    skill: str
    weight: float
    required: bool
    score: float | None
    questions: int
    dimensions: dict[str, float]
    evidence: list[EvaluationEvidence]
    supported: bool


class EvaluationFinding(BaseModel):
    text: str
    skill: str | None
    evidence: list[EvaluationEvidence]
    supported: bool


class EvaluationStatement(BaseModel):
    summary: str
    evidence: list[EvaluationEvidence]
    supported: bool


class CommunicationEvaluation(BaseModel):
    score: float | None
    evidence: list[EvaluationEvidence]
    supported: bool
    summary: EvaluationStatement


class FollowUpPerformance(BaseModel):
    asked: int
    mean: float | None
    main_mean: float | None
    delta: float | None
    summary: EvaluationStatement


class EvaluationCoding(BaseModel):
    """Left for the coding evaluation (SP-16, PRD §47)."""

    status: str
    score: float | None
    source: str


class EvaluationVersions(BaseModel):
    """The §79 versions this evaluation was made with (and a re-run repeats)."""

    prompt: str
    synthesis_prompt: str | None
    rubric: str
    evaluation: str
    model: str | None
    models: list[str]


class EvaluationBody(BaseModel):
    id: UUID
    sequence: int
    versions: EvaluationVersions
    rubric_weights: dict[str, int]
    created_at: datetime
    completed_at: datetime | None
    overall_score: float | None
    communication: CommunicationEvaluation
    skills: list[SkillEvaluation]
    strengths: list[EvaluationFinding]
    knowledge_gaps: list[EvaluationFinding]
    follow_up_performance: FollowUpPerformance
    coding: EvaluationCoding
    flags: list[str]
    questions: list[QuestionEvaluationBrief]


class EvaluationResponse(BaseModel):
    interview_id: UUID
    interview_status: str
    state: EvaluationState
    evaluation: EvaluationBody | None


class RerunResponse(BaseModel):
    id: UUID
    sequence: int
    status: str
    created_at: datetime
    completed_at: datetime | None
    requested_by: UUID | None
    rerun_of: UUID | None
    prompt_version: str
    rubric_version: str
    evaluation_version: str
    within_tolerance: bool | None
    overall_score: float | None
    diff: dict[str, Any] | None
    error: str | None


class RerunQueued(BaseModel):
    action: Literal["evaluate", "rerun"]
    """`evaluate` retries an evaluation that never finished; `rerun` repeats a finished one
    with its pinned versions."""


class HumanScoreBody(BaseModel):
    dimensions: dict[str, float] = Field(min_length=1, max_length=8)
    note: str = Field("", max_length=1000)


class HumanScoreResponse(BaseModel):
    question_id: UUID
    dimensions: dict[str, float]
    note: str
    updated_at: datetime


class EvaluationAgreement(BaseModel):
    n: int
    spearman: float | None
    weighted_kappa: float | None
    mean_abs_diff: float | None
    within_one: float | None


class CalibrationResponse(BaseModel):
    pairs: int
    questions: int
    reviewers: int
    overall: EvaluationAgreement
    by_dimension: dict[str, EvaluationAgreement]
    bias: float | None
    """The AI's mean score minus the reviewers' (positive: the AI scores higher)."""
