"""Request and response bodies for interviews (PRD §24, §25): assignment, the list and detail,
invitations, rescheduling, cancelling and reviewers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

InterviewStatus = Literal[
    "scheduled",
    "invited",
    "in_progress",
    "interrupted",
    "completed",
    "evaluating",
    "evaluated",
    "expired",
    "cancelled",
    "abandoned",
]
StatusGroup = Literal["upcoming", "live", "completed"]


class AssignBody(BaseModel):
    """The window and template every chosen candidate's interview uses."""

    model_config = ConfigDict(extra="forbid")

    starts_at: AwareDatetime
    expires_at: AwareDatetime
    template_id: UUID | None = Field(
        None, description="None: each job's own interview template (PRD §11)."
    )
    template_version: int | None = Field(
        None, ge=1, description="None: the template's current version."
    )
    timezone: str | None = Field(
        None, max_length=64, description="For the invitation's times; the organisation's default."
    )
    reviewer_ids: list[UUID] = Field(default_factory=list, max_length=10)
    invite: bool = Field(True, description="Send the invitation now (otherwise it's scheduled).")


class InterviewCreate(AssignBody):
    application_id: UUID


class BulkInterviewCreate(AssignBody):
    application_ids: list[UUID] = Field(min_length=1, max_length=200)


class PersonRef(BaseModel):
    id: UUID
    name: str


class InterviewSummary(BaseModel):
    id: UUID
    reference: str
    """IV-0042."""
    status: InterviewStatus
    candidate: PersonRef
    job_id: UUID
    job_title: str
    application_id: UUID
    template_id: UUID
    template_version: int
    starts_at: datetime
    expires_at: datetime
    timezone: str
    duration_minutes: int
    proctoring_level: str
    third_eye: str
    created_at: datetime
    updated_at: datetime


class InterviewEventResponse(BaseModel):
    id: UUID
    action: str
    from_status: InterviewStatus | None
    to_status: InterviewStatus
    reason: str | None
    actor_type: Literal["user", "candidate", "system", "agent"]
    actor_id: str | None
    details: dict[str, Any]
    created_at: datetime


class InvitationResponse(BaseModel):
    id: UUID
    kind: Literal["invitation", "reminder", "reschedule", "cancellation"]
    sent_to: str
    locale: str
    contents: dict[str, Any]
    created_at: datetime


class InterviewResponse(InterviewSummary):
    candidate_email: str | None
    template_name: str
    policy: dict[str, Any]
    questions: list[dict[str, Any]]
    reviewers: list[PersonRef]
    events: list[InterviewEventResponse]
    invitations: list[InvitationResponse]
    invited_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    ended_at: datetime | None
    cancel_reason: str | None
    reschedule_count: int


class SkippedApplication(BaseModel):
    application_id: UUID
    code: str
    reason: str


class BulkInterviewResult(BaseModel):
    created: list[InterviewSummary]
    skipped: list[SkippedApplication]


class RescheduleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    starts_at: AwareDatetime
    expires_at: AwareDatetime
    reason: str | None = Field(None, max_length=1000)


class CancelBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=1000)


class ReviewersBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewer_ids: list[UUID] = Field(max_length=10)


class DashboardSummary(BaseModel):
    """PRD §10's figures that have data so far; the rest are absent (the page shows "no data
    yet")."""

    interviews_scheduled: int
    live_interviews: int
    completed_interviews: int
    pending_reviews: int
    """Interviews that have ended and wait for a person to decide (not narrowed by the filters)."""
