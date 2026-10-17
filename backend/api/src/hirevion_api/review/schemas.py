"""Bodies and answers of the review routes (SP-17; PRD §71, §72): the player's media, notes, score
changes, Hiring Manager input, the hiring status, the pending-review queue and the pipeline."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

HiringStatus = Literal[
    "under_review",
    "shortlisted",
    "interview_invited",
    "interview_started",
    "interview_completed",
    "additional_review",
    "selected",
    "rejected",
    "on_hold",
]
Recommendation = Literal["strong_hire", "hire", "hold", "no_hire", "strong_no_hire"]
ScoreScope = Literal["overall", "skill", "communication", "question"]
MediaKind = Literal["camera", "screen", "third_eye", "audio"]


class MediaTrackResponse(BaseModel):
    track: str
    kind: MediaKind
    label: str
    status: str
    stalled: bool
    url: str | None
    """A read-only URL valid for five minutes; none until the track is assembled."""
    container: str | None
    duration_ms: int | None
    started_at: datetime | None
    timeline: dict[str, Any] | None
    """The track's timeline map (`docs/api/contracts/recordings.md`): where each segment sits."""
    gaps: list[dict[str, Any]]


class ReviewMediaResponse(BaseModel):
    interview_id: UUID
    anchor: datetime | None
    """When the interview's clock started: transcript and evidence times count from here."""
    expires_at: datetime
    tracks: list[MediaTrackResponse]


class NoteBody(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    at_ms: int | None = Field(default=None, ge=0)


class NoteResponse(BaseModel):
    id: UUID
    candidate_id: UUID
    interview_id: UUID | None
    author_id: UUID
    author_name: str
    body: str
    at_ms: int | None
    created_at: datetime


class NoteList(BaseModel):
    items: list[NoteResponse]


class ScoreChangeBody(BaseModel):
    scope: ScoreScope
    target: str | None = Field(default=None, max_length=200)
    """The skill's name, or the question's id; none for the overall and communication scores."""
    new_score: float = Field(ge=0, le=10)
    reason: str = Field(min_length=1, max_length=1000)


class ScoreChangeResponse(BaseModel):
    id: UUID
    scope: ScoreScope
    target: str | None
    previous_score: float | None
    new_score: float
    reason: str
    changed_by: UUID
    changed_by_name: str
    created_at: datetime


class ScoreValueResponse(BaseModel):
    ai: float | None
    value: float | None
    """What shows: the latest change, else the AI's."""
    change: ScoreChangeResponse | None


class ScoresResponse(BaseModel):
    interview_id: UUID
    evaluation_id: UUID
    overall: ScoreValueResponse
    communication: ScoreValueResponse
    skills: dict[str, ScoreValueResponse]
    questions: dict[str, ScoreValueResponse]
    changes: list[ScoreChangeResponse]


class HistoryItem(BaseModel):
    id: UUID
    from_status: HiringStatus | None
    to_status: HiringStatus
    source: Literal["system", "user"]
    decision: bool
    reason: str | None
    actor_id: UUID | None
    actor_name: str | None
    interview_id: UUID | None
    created_at: datetime


class HiringInputBody(BaseModel):
    recommendation: Recommendation
    ratings: dict[str, int] = Field(default_factory=dict)
    rationale: str = Field(min_length=1, max_length=4000)


class HiringInputResponse(BaseModel):
    id: UUID
    author_id: UUID
    author_name: str
    interview_id: UUID | None
    recommendation: Recommendation
    ratings: dict[str, int]
    rationale: str
    created_at: datetime


class HiringStatusBody(BaseModel):
    status: HiringStatus
    reason: str | None = Field(default=None, max_length=1000)


class HiringStateResponse(BaseModel):
    application_id: UUID
    candidate_id: UUID
    job_id: UUID
    job_title: str
    status: HiringStatus
    allowed: list[HiringStatus]
    """What this reader may move the application to."""
    has_interview: bool
    decision: HistoryItem | None
    """The latest final decision, if one was made and still stands."""
    history: list[HistoryItem]
    inputs: list[HiringInputResponse]


class PendingReviewItem(BaseModel):
    interview_id: UUID
    reference: str
    application_id: UUID
    candidate_id: UUID
    candidate_name: str
    job_title: str
    hiring_status: HiringStatus
    completed_at: datetime | None
    overall_score: float | None
    evaluated: bool
    unreviewed_critical: int


class PendingReviewList(BaseModel):
    total: int
    items: list[PendingReviewItem]


class PipelineCard(BaseModel):
    application_id: UUID
    candidate_id: UUID
    candidate_name: str
    job_id: UUID
    job_title: str
    interview_id: UUID | None
    moves: list[HiringStatus]


class PipelineColumn(BaseModel):
    status: HiringStatus
    count: int
    cards: list[PipelineCard]


class PipelineResponse(BaseModel):
    columns: list[PipelineColumn]
