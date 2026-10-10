"""Evaluations (SP-10; PRD §44, §70, §79): what the async evaluator concluded about an interview,
the pinned versions it used so it can be repeated, and the reviewers' own scores to compare it
with. The model calls themselves are in `ai_invocations`, found by the evaluation's id in their
`input_refs`."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hirevion_core.db.base import Base, IdMixin, TenantMixin, TimestampMixin

EVALUATION_KINDS = ("initial", "rerun")
EVALUATION_STATUSES = ("running", "ready", "failed")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Evaluation(IdMixin, TenantMixin, TimestampMixin, Base):
    """One evaluation run of an interview. An `initial` one is the interview's evaluation; a
    `rerun` repeats it with the versions it pinned and keeps the difference (`diff`)."""

    __tablename__ = "evaluations"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("interview_id", "sequence"),
        ForeignKeyConstraint(
            ["organization_id", "interview_id"],
            ["interviews.organization_id", "interviews.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "rerun_of"],
            ["evaluations.organization_id", "evaluations.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "created_by"], ["users.organization_id", "users.id"]
        ),
        CheckConstraint(_in("kind", EVALUATION_KINDS), name="kind"),
        CheckConstraint(_in("status", EVALUATION_STATUSES), name="status"),
        # An interview has one initial evaluation, running or ready (a failed one can be retried).
        Index(
            "uq_evaluations_initial_per_interview",
            "interview_id",
            unique=True,
            postgresql_where=sql_text("kind = 'initial' AND status IN ('running', 'ready')"),
        ),
    )

    interview_id: Mapped[UUID]
    sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(Text, server_default="initial")
    rerun_of: Mapped[UUID | None]
    status: Mapped[str] = mapped_column(Text, server_default="running")
    prompt_version: Mapped[str] = mapped_column(Text)
    rubric_version: Mapped[str] = mapped_column(Text)
    evaluation_version: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    pinned: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    """Everything a re-run needs: the rubric's weights, the skills' plan, the synthesis prompt."""
    overall_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    communication_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    skills: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=sql_text("'[]'::jsonb")
    )
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    flags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=sql_text("'{}'::text[]"))
    diff: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None]
    completed_at: Mapped[datetime | None]


class QuestionEvaluation(IdMixin, TenantMixin, Base):
    """One question's eight scores, each with the verified quotes behind it (PRD §44)."""

    __tablename__ = "question_evaluations"
    __table_args__ = (
        UniqueConstraint("evaluation_id", "question_id"),
        ForeignKeyConstraint(
            ["organization_id", "evaluation_id"],
            ["evaluations.organization_id", "evaluations.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "question_id"],
            ["interview_questions.organization_id", "interview_questions.id"],
            ondelete="CASCADE",
        ),
        Index("ix_question_evaluations_interview_id", "interview_id"),
    )

    evaluation_id: Mapped[UUID]
    interview_id: Mapped[UUID]
    question_id: Mapped[UUID]
    skill: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    weight: Mapped[Decimal] = mapped_column(Numeric(3, 1))
    dimensions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=sql_text("'{}'::jsonb")
    )
    overall_score: Mapped[Decimal] = mapped_column(Numeric(4, 2))
    unsupported: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=sql_text("'{}'::text[]")
    )
    missing_concepts: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=sql_text("'{}'::text[]")
    )
    note: Mapped[str] = mapped_column(Text, server_default="")
    flags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=sql_text("'{}'::text[]"))
    model: Mapped[str] = mapped_column(Text)
    input_digest: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class HumanScore(IdMixin, TenantMixin, TimestampMixin, Base):
    """A reviewer's own scores for a question (calibration): per dimension, 0 to 10. One per
    reviewer and question; the reviewer may change theirs."""

    __tablename__ = "human_scores"
    __table_args__ = (
        UniqueConstraint("question_id", "reviewer_id"),
        ForeignKeyConstraint(
            ["organization_id", "interview_id"],
            ["interviews.organization_id", "interviews.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "question_id"],
            ["interview_questions.organization_id", "interview_questions.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "reviewer_id"], ["users.organization_id", "users.id"]
        ),
        Index("ix_human_scores_interview_id", "interview_id"),
    )

    interview_id: Mapped[UUID]
    question_id: Mapped[UUID]
    reviewer_id: Mapped[UUID]
    dimensions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=sql_text("'{}'::jsonb")
    )
    note: Mapped[str] = mapped_column(Text, server_default="")
