"""Request and response bodies for screening configuration, results and actions."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from hirevion_api.candidates.schemas import Stage

Action = Literal[
    "shortlist", "reject", "hold", "review", "assign_recruiter", "assign_hiring_manager"
]


class ScreeningConfigResponse(BaseModel):
    weights: dict[str, int]
    knockouts: dict[str, bool]
    blind: bool
    version: int
    inherited: bool
    """Whether the job uses the organisation's (or the built-in) configuration."""
    source: Literal["job", "organization", "default"]


class ScreeningConfigUpdate(BaseModel):
    """Only the fields sent change; a job's first save starts from what it inherited."""

    model_config = ConfigDict(extra="forbid")

    weights: dict[str, int] | None = None
    knockouts: dict[str, bool] | None = None
    blind: bool | None = None


class ScreenRequest(BaseModel):
    application_ids: list[UUID] | None = Field(
        None, max_length=500, description="Only these; all of the job's otherwise."
    )


class ScreenAccepted(BaseModel):
    queued: int


class ScreeningSummary(BaseModel):
    applications: int
    screened: int
    """Applications with a screening result."""
    waiting: int
    """Applications parsed but not screened yet."""
    stages: dict[str, int]


class CandidateBrief(BaseModel):
    id: UUID
    name: str
    headline: str | None
    location: str | None
    flags: dict[str, Any]


class RankedApplication(BaseModel):
    application_id: UUID
    rank: int | None
    stage: Stage
    score: int | None
    candidate: CandidateBrief
    skill_match: dict[str, Any]
    experience: dict[str, Any]
    knockouts: list[str]
    semantic_similarity: float | None
    recruiter_id: UUID | None
    hiring_manager_id: UUID | None
    screened_at: datetime | None


class ScreeningResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    score: int
    factors: dict[str, Any]
    """Per factor: `score`, `evidence` (quotes from the resume) and `supported`."""
    skill_match: dict[str, Any]
    experience: dict[str, Any]
    strengths: list[str]
    concerns: list[str]
    missing: list[str]
    knockouts: list[str]
    semantic_similarity: float | None
    job_version: int
    config_version: int
    prompt_version: str
    model: str
    created_at: datetime


class HistoryEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_stage: str | None
    to_stage: str | None
    action: str
    reason: str | None
    score: int | None
    rank: int | None
    override: bool
    actor_id: UUID | None
    created_at: datetime


class ApplicationScreening(BaseModel):
    application_id: UUID
    job_id: UUID
    stage: Stage
    rank: int | None
    candidate: CandidateBrief
    result: ScreeningResultResponse | None
    history: list[HistoryEntry]


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    application_ids: list[UUID] = Field(min_length=1, max_length=500)
    action: Action
    reason: str | None = Field(None, max_length=1000)
    user_id: UUID | None = Field(None, description="For the assign actions; null clears.")


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    reason: str | None = Field(None, max_length=1000)


class ApplicationState(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    stage: Stage
    rank: int | None
    recruiter_id: UUID | None
    hiring_manager_id: UUID | None


class ActionResult(BaseModel):
    applications: list[ApplicationState]
