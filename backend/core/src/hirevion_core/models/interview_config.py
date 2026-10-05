from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hirevion_core.db.base import Base, IdMixin, TenantMixin, TimestampMixin

QUESTION_CATEGORIES = ("technical", "coding", "system_design", "resume_based", "custom")
# PRD §22's eight types.
QUESTION_TYPES = (
    "technical",
    "conceptual",
    "scenario",
    "system_design",
    "coding",
    "resume_based",
    "project_based",
    "problem_solving",
)
QUESTION_STATUSES = ("draft", "approved", "archived")
DIFFICULTIES = ("easy", "medium", "hard")
PROCTORING_LEVELS = ("off", "basic", "standard", "strict")
THIRD_EYE_MODES = ("off", "optional", "required")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Question(IdMixin, TenantMixin, TimestampMixin, Base):
    """A library question (PRD §22): a stable identity whose content lives in immutable
    versions. Only approved questions can be used by templates and interviews."""

    __tablename__ = "questions"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        CheckConstraint(_in("category", QUESTION_CATEGORIES), name="category"),
        CheckConstraint(_in("status", QUESTION_STATUSES), name="status"),
        CheckConstraint(_in("source", ("manual", "ai")), name="source"),
    )

    category: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    source: Mapped[str] = mapped_column(Text, server_default="manual")
    current_version: Mapped[int] = mapped_column(Integer, server_default=sql_text("1"))
    created_by: Mapped[UUID | None]
    approved_by: Mapped[UUID | None]
    approved_at: Mapped[datetime | None]


class QuestionVersion(Base):
    """One version of a question: every §22 field. Never changed once written."""

    __tablename__ = "question_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "question_id"],
            ["questions.organization_id", "questions.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(_in("difficulty", DIFFICULTIES), name="difficulty"),
        CheckConstraint(_in("type", QUESTION_TYPES), name="type"),
        Index(
            "ix_question_versions_text_trgm",
            "text",
            postgresql_using="gin",
            postgresql_ops={"text": "gin_trgm_ops"},
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    question_id: Mapped[UUID] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    skill_name: Mapped[str] = mapped_column(Text)
    skill_id: Mapped[UUID | None] = mapped_column(ForeignKey("skills.id"))
    topic: Mapped[str | None] = mapped_column(Text)
    difficulty: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(Text)
    expected_concepts: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=sql_text("'{}'::text[]")
    )
    rubric: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=sql_text("'[]'::jsonb")
    )
    time_limit_seconds: Mapped[int | None] = mapped_column(Integer)
    follow_up_rules: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=sql_text("'[]'::jsonb")
    )
    coding: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    generation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_by: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class InterviewTemplate(IdMixin, TenantMixin, TimestampMixin, Base):
    """A reusable interview design (PRD §21). Interviews pin a version (PRD §80)."""

    __tablename__ = "interview_templates"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        Index(
            "uq_interview_templates_organization_id_name",
            "organization_id",
            sql_text("lower(name)"),
            unique=True,
        ),
        CheckConstraint(_in("status", ("active", "archived")), name="status"),
    )

    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, server_default="")
    status: Mapped[str] = mapped_column(Text, server_default="active")
    current_version: Mapped[int] = mapped_column(Integer, server_default=sql_text("1"))
    created_by: Mapped[UUID | None]


class InterviewTemplateVersion(Base):
    """One version of a template: every §21 field. Never changed once written."""

    __tablename__ = "interview_template_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "template_id"],
            ["interview_templates.organization_id", "interview_templates.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("duration_minutes BETWEEN 15 AND 180", name="duration"),
        CheckConstraint("question_count BETWEEN 1 AND 50", name="count"),
        CheckConstraint(_in("proctoring_level", PROCTORING_LEVELS), name="proctoring"),
        CheckConstraint(_in("third_eye", THIRD_EYE_MODES), name="third_eye"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    template_id: Mapped[UUID] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    duration_minutes: Mapped[int] = mapped_column(Integer)
    question_count: Mapped[int] = mapped_column(Integer)
    skills: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=sql_text("'[]'::jsonb")
    )
    difficulty: Mapped[dict[str, int]] = mapped_column(
        JSONB, server_default=sql_text("'{}'::jsonb")
    )
    question_types: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=sql_text("'{}'::text[]")
    )
    use_resume: Mapped[bool] = mapped_column(Boolean, server_default=true())
    use_jd: Mapped[bool] = mapped_column(Boolean, server_default=true())
    adaptive_follow_ups: Mapped[bool] = mapped_column(Boolean, server_default=true())
    coding: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    proctoring_level: Mapped[str] = mapped_column(Text, server_default="standard")
    third_eye: Mapped[str] = mapped_column(Text, server_default="optional")
    recording: Mapped[dict[str, bool]] = mapped_column(
        JSONB, server_default=sql_text("'{}'::jsonb")
    )
    rubric: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=sql_text("'[]'::jsonb")
    )
    questions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=sql_text("'[]'::jsonb")
    )
    created_by: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class OrganizationSettings(Base):
    """Per-organisation settings that aren't the profile: the interview defaults (SP-06)."""

    __tablename__ = "organization_settings"

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    interview_defaults: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=sql_text("'{}'::jsonb")
    )
    updated_by: Mapped[UUID | None]
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
