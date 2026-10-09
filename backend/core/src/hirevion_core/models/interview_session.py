"""The interview while it happens (SP-09): what the candidate checked and agreed to before it,
the engine's checkpoint, every question asked and answer given, workspace snapshots, and the
two-sided transcript (PRD §29, §30, §34 to §43, §83, §89)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hirevion_core.db.base import Base, IdMixin, TenantMixin, TimestampMixin
from hirevion_core.ids import uuid7

CHECK_STATUSES = ("pass", "warn", "fail", "skipped")
ACCOMMODATION_STATUSES = ("requested", "approved", "declined")
ANSWER_MODES = ("voice", "text")
QUESTION_KINDS = ("introduction", "main", "follow_up", "coding", "final")
QUESTION_SOURCES = ("pinned", "library", "generated", "resume", "follow_up", "faq", "system")
QUESTION_STATES = ("asked", "answered", "timed_out", "skipped")
ANSWER_QUALITIES = ("strong", "partial", "weak", "no_answer")
WORKSPACE_KINDS = ("code", "whiteboard")
SPEAKERS = ("ai", "candidate")
TRANSCRIPT_STATUSES = ("pending", "ready", "failed")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _interview_fk() -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["organization_id", "interview_id"],
        ["interviews.organization_id", "interviews.id"],
        ondelete="CASCADE",
    )


class SystemCheckResult(IdMixin, TenantMixin, Base):
    """One run of the desktop's system check (PRD §29), as reported. Never changed."""

    __tablename__ = "system_check_results"
    __table_args__ = (
        _interview_fk(),
        Index("ix_system_check_results_interview_id", "interview_id"),
    )

    interview_id: Mapped[UUID]
    app_version: Mapped[str] = mapped_column(Text)
    os: Mapped[str] = mapped_column(Text)
    results: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=sql_text("'[]'::jsonb")
    )
    passed: Mapped[bool] = mapped_column(Boolean)
    failed_mandatory: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=sql_text("'{}'::text[]")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Consent(IdMixin, TenantMixin, Base):
    """The candidate's answer to each purpose of the notice they were shown (PRD §30, §83),
    with where it came from. Never changed: a new answer is a new row."""

    __tablename__ = "consents"
    __table_args__ = (_interview_fk(), Index("ix_consents_interview_id", "interview_id"))

    interview_id: Mapped[UUID]
    candidate_id: Mapped[UUID]
    notice_version: Mapped[str] = mapped_column(Text)
    items: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=sql_text("'[]'::jsonb")
    )
    complete: Mapped[bool] = mapped_column(Boolean)
    missing: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=sql_text("'{}'::text[]"))
    ip: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Accommodation(IdMixin, TenantMixin, TimestampMixin, Base):
    """A candidate's request for adjustments, and the recruiter's decision on it."""

    __tablename__ = "accommodations"
    __table_args__ = (
        _interview_fk(),
        ForeignKeyConstraint(
            ["organization_id", "decided_by"], ["users.organization_id", "users.id"]
        ),
        CheckConstraint(_in("status", ACCOMMODATION_STATUSES), name="status"),
        Index("ix_accommodations_interview_id", "interview_id"),
    )

    interview_id: Mapped[UUID]
    kinds: Mapped[list[str]] = mapped_column(ARRAY(Text))
    note: Mapped[str] = mapped_column(Text, server_default="")
    status: Mapped[str] = mapped_column(Text, server_default="requested")
    approved_kinds: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=sql_text("'{}'::text[]")
    )
    decision_note: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[UUID | None]
    decided_at: Mapped[datetime | None]


class InterviewSession(TenantMixin, TimestampMixin, Base):
    """The engine's side of one interview: its checkpoint (`state`, written every turn with an
    optimistic `state_seq`), the clock, the room and the interruptions."""

    __tablename__ = "interview_sessions"
    __table_args__ = (
        _interview_fk(),
        CheckConstraint(_in("mode", ANSWER_MODES), name="mode"),
        CheckConstraint("paused_seconds >= 0", name="paused_seconds"),
    )

    interview_id: Mapped[UUID] = mapped_column(primary_key=True)
    mode: Mapped[str] = mapped_column(Text, server_default="voice")
    room: Mapped[str] = mapped_column(Text)
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    state_seq: Mapped[int] = mapped_column(Integer, server_default=sql_text("0"))
    started_at: Mapped[datetime]
    deadline_at: Mapped[datetime]
    paused_seconds: Mapped[int] = mapped_column(Integer, server_default=sql_text("0"))
    interruptions: Mapped[int] = mapped_column(Integer, server_default=sql_text("0"))
    reconnects: Mapped[int] = mapped_column(Integer, server_default=sql_text("0"))
    connected_at: Mapped[datetime | None]
    """The candidate's latest start or reconnect: an older "left the room" event is stale."""
    system_check_id: Mapped[UUID | None]
    consent_id: Mapped[UUID | None]
    agent_dispatch_id: Mapped[str | None] = mapped_column(Text)
    ended_at: Mapped[datetime | None]


class InterviewQuestion(IdMixin, TenantMixin, Base):
    """A question as it was asked, in order, with where it came from (PRD §36): a library or
    pinned question's version, the resume evidence it quotes, or the rule that generated it."""

    __tablename__ = "interview_questions"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("interview_id", "position"),
        _interview_fk(),
        CheckConstraint(_in("kind", QUESTION_KINDS), name="kind"),
        CheckConstraint(_in("source", QUESTION_SOURCES), name="source"),
        CheckConstraint(_in("status", QUESTION_STATES), name="status"),
    )

    interview_id: Mapped[UUID]
    position: Mapped[int] = mapped_column(Integer)
    parent_id: Mapped[UUID | None]
    kind: Mapped[str] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(Text)
    skill: Mapped[str | None] = mapped_column(Text)
    topic: Mapped[str | None] = mapped_column(Text)
    difficulty: Mapped[str | None] = mapped_column(Text)
    type: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    source_ref: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=sql_text("'{}'::jsonb")
    )
    expected_concepts: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=sql_text("'{}'::text[]")
    )
    time_limit_seconds: Mapped[int | None] = mapped_column(Integer)
    workspace: Mapped[str] = mapped_column(Text, server_default="none")
    languages: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=sql_text("'{}'::text[]")
    )
    status: Mapped[str] = mapped_column(Text, server_default="asked")
    asked_at: Mapped[datetime]
    closed_at: Mapped[datetime | None]


class InterviewAnswer(IdMixin, TenantMixin, Base):
    """What the candidate answered to one question, and the live analysis that steered the
    interview (PRD §38). SP-10's evaluation is kept apart from it."""

    __tablename__ = "interview_answers"
    __table_args__ = (
        _interview_fk(),
        ForeignKeyConstraint(
            ["organization_id", "question_id"],
            ["interview_questions.organization_id", "interview_questions.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(_in("mode", ANSWER_MODES), name="mode"),
        CheckConstraint(f"quality IS NULL OR {_in('quality', ANSWER_QUALITIES)}", name="quality"),
        Index("ix_interview_answers_interview_id", "interview_id"),
        Index("ix_interview_answers_question_id", "question_id"),
    )

    interview_id: Mapped[UUID]
    question_id: Mapped[UUID]
    mode: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime | None]
    ended_at: Mapped[datetime]
    late: Mapped[bool] = mapped_column(Boolean, server_default=false())
    analysis: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    quality: Mapped[str | None] = mapped_column(Text)
    flags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=sql_text("'{}'::text[]"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class WorkspaceSnapshot(IdMixin, TenantMixin, Base):
    """The code or whiteboard the candidate had for a question when the desktop sent it."""

    __tablename__ = "workspace_snapshots"
    __table_args__ = (
        _interview_fk(),
        ForeignKeyConstraint(
            ["organization_id", "question_id"],
            ["interview_questions.organization_id", "interview_questions.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(_in("kind", WORKSPACE_KINDS), name="kind"),
        Index("ix_workspace_snapshots_interview_id", "interview_id"),
    )

    interview_id: Mapped[UUID]
    question_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Transcript(TenantMixin, TimestampMixin, Base):
    """The interview's transcript artifacts (JSON, VTT, TXT) once it has ended (PRD §43, §85)."""

    __tablename__ = "transcripts"
    __table_args__ = (
        _interview_fk(),
        CheckConstraint(_in("status", TRANSCRIPT_STATUSES), name="status"),
    )

    interview_id: Mapped[UUID] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    segment_count: Mapped[int] = mapped_column(Integer, server_default=sql_text("0"))
    artifacts: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))


class TranscriptSegment(Base):
    """One utterance, by the AI or the candidate (PRD §41): partitioned by month on
    `occurred_at`, written in the turn's transaction and never changed."""

    __tablename__ = "transcript_segments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "interview_id"],
            ["interviews.organization_id", "interviews.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(_in("speaker", SPEAKERS), name="speaker"),
        CheckConstraint("start_ms >= 0 AND end_ms >= start_ms", name="times"),
        Index("ix_transcript_segments_interview_id_seq", "interview_id", "seq"),
        {"postgresql_partition_by": "RANGE (occurred_at)"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    occurred_at: Mapped[datetime] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    interview_id: Mapped[UUID]
    seq: Mapped[int] = mapped_column(Integer)
    speaker: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    question_id: Mapped[UUID | None]
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
