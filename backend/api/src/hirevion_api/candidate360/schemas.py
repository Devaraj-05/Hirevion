"""Candidate 360 and the unified timeline (SP-17; PRD §20, §98)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

from hirevion_api.review.schemas import HiringStatus, MediaKind, NoteResponse, ScoreValueResponse

TimelineSource = Literal[
    "screening",
    "interview",
    "transcript",
    "coding",
    "proctoring",
    "recording",
    "evaluation",
    "recruiter",
]


class ApplicationItem(BaseModel):
    application_id: UUID
    job_id: UUID
    job_title: str
    stage: str
    hiring_status: HiringStatus
    rank: int | None


class ScreeningItem(BaseModel):
    application_id: UUID
    job_id: UUID
    job_title: str
    score: int
    rank: int | None
    strengths: list[str]
    concerns: list[str]
    missing: list[str]
    knockouts: list[str]
    screened_at: datetime


class EventCounts(BaseModel):
    critical: int
    warning: int
    info: int
    reviewed: int


class RecordingBrief(BaseModel):
    track: str
    kind: MediaKind
    label: str
    status: str
    duration_ms: int | None


class ExportBrief(BaseModel):
    id: UUID
    kind: str
    created_at: datetime


class SkillScore(BaseModel):
    skill: str
    score: ScoreValueResponse


class EvaluationBrief(BaseModel):
    state: Literal["none", "ready"]
    overall: ScoreValueResponse | None
    communication: ScoreValueResponse | None
    skills: list[SkillScore]
    flags: list[str]
    strengths: list[str]
    knowledge_gaps: list[str]


class InterviewHistoryItem(BaseModel):
    interview_id: UUID
    reference: str
    application_id: UUID
    job_id: UUID
    job_title: str
    template_name: str
    status: str
    hiring_status: HiringStatus
    starts_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    evaluation: EvaluationBrief
    proctoring: EventCounts | None
    """None for a reader who may not see proctoring."""
    recordings: list[RecordingBrief]
    candidate_report_status: Literal["none", "draft", "released", "withdrawn"]
    code_snapshots: int
    exports: list[ExportBrief]


class SkillInterviewScore(BaseModel):
    interview_id: UUID
    reference: str
    score: float | None


class SkillRow(BaseModel):
    skill: str
    on_resume: bool
    resume_years: float | None
    interviews: list[SkillInterviewScore]


class TabAccess(BaseModel):
    """Which of the thirteen tabs hold data this reader may see."""

    interviews: bool
    proctoring: bool
    recordings: bool
    reports: bool
    notes: bool


class Candidate360Response(BaseModel):
    candidate_id: UUID
    name: str
    access: TabAccess
    applications: list[ApplicationItem]
    screening: list[ScreeningItem]
    interviews: list[InterviewHistoryItem]
    skills: list[SkillRow]
    notes: list[NoteResponse]


class TimelineItem(BaseModel):
    at: datetime
    source: TimelineSource
    kind: str
    title: str
    detail: str | None
    severity: Literal["INFO", "WARNING", "CRITICAL"] | None
    interview_id: UUID | None
    offset_ms: int | None
    actor: str | None
    ref: dict[str, Any]


class TimelineResponse(BaseModel):
    items: list[TimelineItem]
    """Newest first."""
    next_before: datetime | None
    """Pass as `before` to read the next, older page; none at the end."""
