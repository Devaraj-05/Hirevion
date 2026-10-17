"""Reports, review and the hiring workflow (SP-17; PRD §69, §71, §72, §99).

- `application_status_history`: every change of an application's hiring status (PRD §72), with who
  made it and why. Insert-only.
- `hiring_inputs`: a Hiring Manager's structured recommendation. Insert-only; a changed mind is a
  new row and the latest per author counts.
- `candidate_notes`: a recruiter's or reviewer's note on a candidate, optionally on an interview
  and a moment of it. Insert-only.
- `score_changes`: a person's change of a score the AI gave, with the reason. The evaluation
  itself is never edited. Insert-only.
- `reports`: the candidate-visible report of an interview (PRD §99): drafted, approved by a
  recruiter, frozen at release.
- `report_exports`: a PDF of a report, kept so viewing and downloading it can be audited.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hirevion_core.db.base import Base, IdMixin, TenantMixin, TimestampMixin
from hirevion_core.models.candidate import HIRING_STATUSES

STATUS_SOURCES = ("system", "user")
RECOMMENDATIONS = ("strong_hire", "hire", "hold", "no_hire", "strong_no_hire")
SCORE_SCOPES = ("overall", "skill", "communication", "question")
REPORT_KINDS = ("interview", "proctoring", "coding", "candidate", "candidate_visible")
REPORT_AUDIENCES = ("internal", "candidate")
EXPORT_STATUSES = ("ready", "failed")
CANDIDATE_REPORT_STATUSES = ("draft", "released", "withdrawn")
NOTE_MAX = 4000
# Rows written in one transaction keep their order, so the history tables stamp each row
# with the clock rather than the transaction's start.
_NOW = sql_text("clock_timestamp()")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class ApplicationStatusHistory(IdMixin, TenantMixin, Base):
    """One change of an application's hiring status. `source` is `system` for what follows from
    the interview itself (invited, started, completed) and `user` for a person's act, which
    names them; `decision` marks a final decision (selected or rejected after an interview)."""

    __tablename__ = "application_status_history"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "application_id"],
            ["applications.organization_id", "applications.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "interview_id"],
            ["interviews.organization_id", "interviews.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "actor_id"], ["users.organization_id", "users.id"]
        ),
        CheckConstraint(_in("to_status", HIRING_STATUSES), name="to_status"),
        CheckConstraint(_in("source", STATUS_SOURCES), name="source"),
        Index("ix_application_status_history_application_id", "application_id", "created_at"),
    )

    application_id: Mapped[UUID]
    interview_id: Mapped[UUID | None]
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    actor_id: Mapped[UUID | None]
    decision: Mapped[bool] = mapped_column(Boolean, server_default=false())
    created_at: Mapped[datetime] = mapped_column(server_default=_NOW)


class HiringInput(IdMixin, TenantMixin, Base):
    """A Hiring Manager's recommendation about an application (PRD §6), with the reasons. It
    informs the person who decides and never moves the status by itself."""

    __tablename__ = "hiring_inputs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "application_id"],
            ["applications.organization_id", "applications.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "interview_id"],
            ["interviews.organization_id", "interviews.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "author_id"], ["users.organization_id", "users.id"]
        ),
        CheckConstraint(_in("recommendation", RECOMMENDATIONS), name="recommendation"),
        CheckConstraint("length(btrim(rationale)) > 0", name="rationale"),
        Index("ix_hiring_inputs_application_id", "application_id", "created_at"),
    )

    application_id: Mapped[UUID]
    interview_id: Mapped[UUID | None]
    author_id: Mapped[UUID]
    recommendation: Mapped[str] = mapped_column(Text)
    ratings: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    """Optional 1 to 5 ratings: `technical`, `communication`, `role_fit`."""
    rationale: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=_NOW)


class CandidateNote(IdMixin, TenantMixin, Base):
    """A note about a candidate (PRD §71 "add notes"), on an interview and a moment of it when
    taken in the review workspace. Internal: the portal never reads this table."""

    __tablename__ = "candidate_notes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "candidate_id"],
            ["candidates.organization_id", "candidates.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "application_id"],
            ["applications.organization_id", "applications.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "interview_id"],
            ["interviews.organization_id", "interviews.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "author_id"], ["users.organization_id", "users.id"]
        ),
        CheckConstraint(f"length(btrim(body)) BETWEEN 1 AND {NOTE_MAX}", name="body"),
        CheckConstraint("at_ms IS NULL OR at_ms >= 0", name="at_ms"),
        Index("ix_candidate_notes_candidate_id", "candidate_id", "created_at"),
        Index("ix_candidate_notes_interview_id", "interview_id", "created_at"),
    )

    candidate_id: Mapped[UUID]
    application_id: Mapped[UUID | None]
    interview_id: Mapped[UUID | None]
    author_id: Mapped[UUID]
    body: Mapped[str] = mapped_column(Text)
    at_ms: Mapped[int | None] = mapped_column(BigInteger)
    """Where in the interview the note was taken, in milliseconds from its start."""
    created_at: Mapped[datetime] = mapped_column(server_default=_NOW)


class ScoreChange(IdMixin, TenantMixin, Base):
    """A person's change of one of the evaluation's scores (PRD §97 "Score modified"). The AI's
    own score stays in `evaluations`; reports show both, with the reason."""

    __tablename__ = "score_changes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "interview_id"],
            ["interviews.organization_id", "interviews.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "evaluation_id"],
            ["evaluations.organization_id", "evaluations.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "changed_by"], ["users.organization_id", "users.id"]
        ),
        CheckConstraint(_in("scope", SCORE_SCOPES), name="scope"),
        CheckConstraint("new_score BETWEEN 0 AND 10", name="new_score"),
        CheckConstraint("length(btrim(reason)) > 0", name="reason"),
        CheckConstraint(
            "(scope IN ('overall', 'communication')) = (target IS NULL)", name="target"
        ),
        Index("ix_score_changes_interview_id", "interview_id", "created_at"),
    )

    interview_id: Mapped[UUID]
    evaluation_id: Mapped[UUID]
    scope: Mapped[str] = mapped_column(Text)
    target: Mapped[str | None] = mapped_column(Text)
    """The skill's name, or the question's id, for those scopes."""
    previous_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    new_score: Mapped[Decimal] = mapped_column(Numeric(4, 2))
    reason: Mapped[str] = mapped_column(Text)
    changed_by: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(server_default=_NOW)


class Report(IdMixin, TenantMixin, TimestampMixin, Base):
    """The candidate-visible report of an interview (PRD §99). `items` is the draft a recruiter
    edits; approving freezes what the organisation allows into `released_items`, which is all
    the portal ever reads."""

    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("interview_id"),
        ForeignKeyConstraint(
            ["organization_id", "interview_id"],
            ["interviews.organization_id", "interviews.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "application_id"],
            ["applications.organization_id", "applications.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "approved_by"], ["users.organization_id", "users.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "withdrawn_by"], ["users.organization_id", "users.id"]
        ),
        CheckConstraint(_in("status", CANDIDATE_REPORT_STATUSES), name="status"),
        CheckConstraint(
            "status <> 'released' OR (released_items IS NOT NULL AND approved_by IS NOT NULL)",
            name="released",
        ),
    )

    interview_id: Mapped[UUID]
    application_id: Mapped[UUID]
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    items: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    released_items: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    evaluation_id: Mapped[UUID | None]
    """The evaluation the draft was written from."""
    approved_by: Mapped[UUID | None]
    approved_at: Mapped[datetime | None]
    withdrawn_by: Mapped[UUID | None]
    withdrawn_at: Mapped[datetime | None]
    withdrawn_reason: Mapped[str | None] = mapped_column(Text)


class ReportExport(IdMixin, TenantMixin, Base):
    """A PDF of a report, rendered once and kept. `document_sha256` is the report document it
    was rendered from, so an export can be shown to match what was on screen."""

    __tablename__ = "report_exports"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "interview_id"],
            ["interviews.organization_id", "interviews.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "candidate_id"],
            ["candidates.organization_id", "candidates.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "requested_by"], ["users.organization_id", "users.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "candidate_account_id"],
            ["candidate_accounts.organization_id", "candidate_accounts.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(_in("kind", REPORT_KINDS), name="kind"),
        CheckConstraint(_in("audience", REPORT_AUDIENCES), name="audience"),
        CheckConstraint(_in("status", EXPORT_STATUSES), name="status"),
        CheckConstraint("interview_id IS NOT NULL OR candidate_id IS NOT NULL", name="subject"),
        Index("ix_report_exports_interview_id", "interview_id", "created_at"),
        Index("ix_report_exports_candidate_id", "candidate_id", "created_at"),
    )

    kind: Mapped[str] = mapped_column(Text)
    audience: Mapped[str] = mapped_column(Text, server_default="internal")
    interview_id: Mapped[UUID | None]
    candidate_id: Mapped[UUID | None]
    requested_by: Mapped[UUID | None]
    candidate_account_id: Mapped[UUID | None]
    status: Mapped[str] = mapped_column(Text, server_default="ready")
    blob_path: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(Text, server_default="application/pdf")
    bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(Text)
    document_sha256: Mapped[str] = mapped_column(Text)
    renderer: Mapped[str] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(Text, server_default="en-IN")
    created_at: Mapped[datetime] = mapped_column(server_default=_NOW)
