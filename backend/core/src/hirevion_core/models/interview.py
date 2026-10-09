from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hirevion_core.db.base import Base, IdMixin, TenantMixin, TimestampMixin

# The interview lifecycle (master plan §7): Scheduled → Invited → In Progress ⇄ Interrupted →
# Completed → Evaluating → Evaluated; or Expired, Cancelled, Abandoned.
INTERVIEW_STATUSES = (
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
)
# An application has at most one interview in these at a time.
ACTIVE_STATUSES = ("scheduled", "invited", "in_progress", "interrupted")
EVENT_ACTORS = ("user", "candidate", "system", "agent")
INVITATION_KINDS = ("invitation", "reminder", "reschedule", "cancellation")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Interview(IdMixin, TenantMixin, TimestampMixin, Base):
    """An interview assigned to a candidate for a job (PRD §24): it pins a template version and
    a snapshot of its policy, so later edits to the template never reach it (PRD §80). It copies
    the job's team and recruiter, which the resource scope filters on."""

    __tablename__ = "interviews"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "number"),
        ForeignKeyConstraint(
            ["organization_id", "application_id"],
            ["applications.organization_id", "applications.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "candidate_id"],
            ["candidates.organization_id", "candidates.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "job_id"], ["jobs.organization_id", "jobs.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["organization_id", "template_id"],
            ["interview_templates.organization_id", "interview_templates.id"],
        ),
        ForeignKeyConstraint(
            ["template_id", "template_version"],
            ["interview_template_versions.template_id", "interview_template_versions.version"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "candidate_account_id"],
            ["candidate_accounts.organization_id", "candidate_accounts.id"],
        ),
        ForeignKeyConstraint(["organization_id", "team_id"], ["teams.organization_id", "teams.id"]),
        ForeignKeyConstraint(
            ["organization_id", "recruiter_id"], ["users.organization_id", "users.id"]
        ),
        CheckConstraint(_in("status", INTERVIEW_STATUSES), name="status"),
        CheckConstraint("starts_at < expires_at", name="window"),
        CheckConstraint("duration_minutes BETWEEN 15 AND 360", name="duration"),
        CheckConstraint("reschedule_count >= 0", name="reschedule_count"),
        Index("ix_interviews_application_id", "application_id"),
        Index("ix_interviews_candidate_id", "candidate_id"),
        Index("ix_interviews_status_expires_at", "status", "expires_at"),
        Index(
            "uq_interviews_active_application",
            "application_id",
            unique=True,
            postgresql_where=text(_in("status", ACTIVE_STATUSES)),
        ),
    )

    number: Mapped[int] = mapped_column(Integer)
    application_id: Mapped[UUID]
    candidate_id: Mapped[UUID]
    job_id: Mapped[UUID]
    candidate_account_id: Mapped[UUID | None]
    template_id: Mapped[UUID]
    template_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, server_default="scheduled")
    starts_at: Mapped[datetime]
    expires_at: Mapped[datetime]
    timezone: Mapped[str] = mapped_column(Text, server_default="Asia/Kolkata")
    locale: Mapped[str] = mapped_column(Text, server_default="en-IN")
    duration_minutes: Mapped[int] = mapped_column(Integer)
    policy: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    questions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    team_id: Mapped[UUID | None]
    recruiter_id: Mapped[UUID | None]
    created_by: Mapped[UUID | None]
    invited_at: Mapped[datetime | None]
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    ended_at: Mapped[datetime | None]
    # When the candidate last dropped out (SP-09): the resume policy's grace runs from here.
    interrupted_at: Mapped[datetime | None]
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    start_reminder_sent_at: Mapped[datetime | None]
    expiry_reminder_sent_at: Mapped[datetime | None]
    reschedule_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class InterviewEvent(IdMixin, TenantMixin, Base):
    """Every change to an interview's status, and the other things that happened to it (an
    invitation sent, a reschedule), with who did it."""

    __tablename__ = "interview_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "interview_id"],
            ["interviews.organization_id", "interviews.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(_in("actor_type", EVENT_ACTORS), name="actor_type"),
    )

    interview_id: Mapped[UUID] = mapped_column(index=True)
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    actor_type: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class InterviewReviewer(Base):
    """Someone who reviews an interview (PRD §6 Interviewer/Reviewer); interviewers see only
    the interviews they review."""

    __tablename__ = "interview_reviewers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "interview_id"],
            ["interviews.organization_id", "interviews.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["users.organization_id", "users.id"],
            ondelete="CASCADE",
        ),
        Index("ix_interview_reviewers_user_id", "user_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    interview_id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(primary_key=True)
    created_by: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Invitation(IdMixin, TenantMixin, Base):
    """An email sent to the candidate about an interview, with the PRD §25 contents it held."""

    __tablename__ = "invitations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "interview_id"],
            ["interviews.organization_id", "interviews.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(_in("kind", INVITATION_KINDS), name="kind"),
    )

    interview_id: Mapped[UUID] = mapped_column(index=True)
    kind: Mapped[str] = mapped_column(Text)
    sent_to: Mapped[str] = mapped_column(CITEXT)
    locale: Mapped[str] = mapped_column(Text)
    contents: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_by: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
