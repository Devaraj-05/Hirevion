"""Proctoring (SP-14, PRD §54 to §67): the platform's catalogue of application rules, the proctor
session of an interview with the policy it is pinned to, the events judged under that policy,
their evidence, and the recruiter's reviews of them."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hirevion_core.db.base import Base, IdMixin, TenantMixin, TimestampMixin

SESSION_STATUSES = ("open", "closed")
SEVERITIES = ("INFO", "WARNING", "CRITICAL")
ORIGINS = ("client", "server")
PHASES = ("started", "escalated", "ended")
REVIEW_STATUSES = ("pending", "confirmed", "false_positive", "not_relevant")
EVIDENCE_KINDS = (
    "screenshot",
    "video_segment",
    "camera_segment",
    "third_eye_segment",
    "screen_segment",
    "transcript_segment",
    "process_metadata",
)
RULE_ACTIONS = ("block", "allow")
RULE_MATCHES = ("name", "path", "publisher", "signature", "hash", "window_title")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class AppCategory(Base):
    """A kind of application the policy can block (PRD §61): remote access, meetings, AI
    assistants and overlays, messaging, screen recorders, virtual machines. `severity` is what a
    hit on a blocking rule in the category is judged as. Platform-wide, so it has no tenant."""

    __tablename__ = "app_categories"
    __table_args__ = (CheckConstraint(_in("severity", ("WARNING", "CRITICAL")), name="severity"),)

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, server_default="")
    severity: Mapped[str] = mapped_column(Text, server_default="CRITICAL")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AppRule(IdMixin, TimestampMixin, Base):
    """One application rule (PRD §61). `organization_id` is NULL for the platform's catalogue,
    which every organisation reads. A blocking rule never matches on the name alone: a `name`
    rule needs further `conditions` (publisher, signature, hash, path or window title)."""

    __tablename__ = "app_rules"
    __table_args__ = (
        CheckConstraint(_in("action", RULE_ACTIONS), name="action"),
        CheckConstraint(_in("match", RULE_MATCHES), name="match"),
        CheckConstraint(
            "action = 'allow' OR match <> 'name' OR jsonb_array_length(conditions) > 0",
            name="name_alone",
        ),
        Index("ix_app_rules_organization_id", "organization_id"),
    )

    organization_id: Mapped[UUID | None] = mapped_column(ForeignKey("organizations.id"))
    category_key: Mapped[str | None] = mapped_column(ForeignKey("app_categories.key"))
    action: Mapped[str] = mapped_column(Text, server_default="block")
    match: Mapped[str] = mapped_column(Text)
    value: Mapped[str] = mapped_column(Text)
    conditions: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB, server_default=sql_text("'[]'::jsonb")
    )
    label: Mapped[str] = mapped_column(Text, server_default="")
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("true"))


class ProctorSession(IdMixin, TenantMixin, TimestampMixin, Base):
    """The proctoring of one interview: the policy it is pinned to, how far the device's events
    have arrived (`acked_through`, `gaps`), its latest heartbeat and what the server observes."""

    __tablename__ = "proctor_sessions"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("interview_id"),
        ForeignKeyConstraint(
            ["organization_id", "interview_id"],
            ["interviews.organization_id", "interviews.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(_in("status", SESSION_STATUSES), name="status"),
        CheckConstraint("acked_through >= 0 AND max_seq >= acked_through", name="sequence"),
        Index(
            "ix_proctor_sessions_watch_at", "watch_at", postgresql_where=sql_text("status = 'open'")
        ),
    )

    interview_id: Mapped[UUID]
    status: Mapped[str] = mapped_column(Text, server_default="open")
    app_version: Mapped[str] = mapped_column(Text, server_default="")
    level: Mapped[str] = mapped_column(Text)
    policy_version: Mapped[int] = mapped_column(Integer)
    policy: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    opened_at: Mapped[datetime] = mapped_column(server_default=func.now())
    closed_at: Mapped[datetime | None]
    acked_through: Mapped[int] = mapped_column(BigInteger, server_default=sql_text("0"))
    max_seq: Mapped[int] = mapped_column(BigInteger, server_default=sql_text("0"))
    gaps: Mapped[list[list[int]]] = mapped_column(JSONB, server_default=sql_text("'[]'::jsonb"))
    last_heartbeat_at: Mapped[datetime | None]
    heartbeats: Mapped[int] = mapped_column(Integer, server_default=sql_text("0"))
    last_status: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=sql_text("'{}'::jsonb")
    )
    observed: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    nudges: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    watch_at: Mapped[datetime | None]
    """When the watcher next has to look at this session (a missed heartbeat, an open channel)."""


class ProctorEvent(IdMixin, TenantMixin, Base):
    """One proctoring event as PRD §67 describes it: the event, its time and length, confidence,
    evidence (in `proctor_evidence`), plus source, severity, the session's sequence number and
    the policy version. An episode the face module reports in phases is one row, updated in
    place. Reviewed events stay: `review_status` records what the recruiter decided."""

    __tablename__ = "proctor_events"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "proctor_session_id"],
            ["proctor_sessions.organization_id", "proctor_sessions.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "interview_id"],
            ["interviews.organization_id", "interviews.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(_in("severity", SEVERITIES), name="severity"),
        CheckConstraint(_in("origin", ORIGINS), name="origin"),
        CheckConstraint(_in("review_status", REVIEW_STATUSES), name="review_status"),
        CheckConstraint(f"phase IS NULL OR {_in('phase', PHASES)}", name="phase"),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="duration"),
        Index("ix_proctor_events_interview_id_started_at", "interview_id", "started_at", "id"),
        Index("ix_proctor_events_session_id_event", "proctor_session_id", "event", "started_at"),
        Index("ix_proctor_events_severity", "organization_id", "severity", "review_status"),
        Index(
            "uq_proctor_events_session_seq",
            "proctor_session_id",
            "seq",
            unique=True,
            postgresql_where=sql_text("seq IS NOT NULL"),
        ),
        Index(
            "uq_proctor_events_episode",
            "proctor_session_id",
            "event",
            "started_at",
            unique=True,
            postgresql_where=sql_text("phase IS NOT NULL AND origin = 'client'"),
        ),
    )

    proctor_session_id: Mapped[UUID]
    interview_id: Mapped[UUID]
    seq: Mapped[int | None] = mapped_column(BigInteger)
    last_seq: Mapped[int | None] = mapped_column(BigInteger)
    origin: Mapped[str] = mapped_column(Text, server_default="client")
    event: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime]
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    ongoing: Mapped[bool] = mapped_column(Boolean, server_default=false())
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    severity: Mapped[str] = mapped_column(Text)
    phase: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    policy_version: Mapped[int] = mapped_column(Integer)
    review_status: Mapped[str] = mapped_column(Text, server_default="pending")
    received_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class ProctorEvidence(IdMixin, TenantMixin, Base):
    """A piece of evidence (PRD §67). A snapshot's row exists from the moment the desktop is
    given an upload slot (`proctor_event_id` empty) and is linked when an event names its blob;
    segments and transcript or process references are added by the server."""

    __tablename__ = "proctor_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "proctor_session_id"],
            ["proctor_sessions.organization_id", "proctor_sessions.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "proctor_event_id"],
            ["proctor_events.organization_id", "proctor_events.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(_in("kind", EVIDENCE_KINDS), name="kind"),
        CheckConstraint(_in("origin", ORIGINS), name="origin"),
        Index("ix_proctor_evidence_event_id", "proctor_event_id"),
        Index("ix_proctor_evidence_session_id", "proctor_session_id"),
        Index(
            "uq_proctor_evidence_blob",
            "proctor_session_id",
            "blob_path",
            unique=True,
            postgresql_where=sql_text("blob_path IS NOT NULL"),
        ),
    )

    proctor_session_id: Mapped[UUID]
    interview_id: Mapped[UUID]
    proctor_event_id: Mapped[UUID | None]
    kind: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(Text, server_default="client")
    blob_path: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(Text)
    bytes: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(Text)
    window_start: Mapped[datetime | None]
    window_end: Mapped[datetime | None]
    ref: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ProctorEventReview(IdMixin, TenantMixin, Base):
    """A recruiter's decision about an event: confirmed, a false positive or not relevant, with
    the reason. Insert-only: a changed mind is a new row, and the event keeps the latest."""

    __tablename__ = "proctor_event_reviews"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "proctor_event_id"],
            ["proctor_events.organization_id", "proctor_events.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "reviewer_id"], ["users.organization_id", "users.id"]
        ),
        CheckConstraint(
            _in("outcome", ("confirmed", "false_positive", "not_relevant")), name="outcome"
        ),
        CheckConstraint("length(btrim(reason)) > 0", name="reason"),
        Index("ix_proctor_event_reviews_event_id", "proctor_event_id", "created_at"),
    )

    proctor_event_id: Mapped[UUID]
    interview_id: Mapped[UUID]
    reviewer_id: Mapped[UUID]
    outcome: Mapped[str] = mapped_column(Text)
    previous: Mapped[str] = mapped_column(Text, server_default="pending")
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
