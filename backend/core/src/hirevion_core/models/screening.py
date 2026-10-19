from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hirevion_core.db.base import Base, IdMixin, TenantMixin, TimestampMixin


class ScreeningConfig(IdMixin, TenantMixin, TimestampMixin, Base):
    """How a job's candidates are weighed (PRD §17): the organisation's default (`job_id` null)
    or a job's own. Each save increments `version`; results record the version they used."""

    __tablename__ = "screening_configs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "job_id"], ["jobs.organization_id", "jobs.id"], ondelete="CASCADE"
        ),
        Index(
            "uq_screening_configs_organization_default",
            "organization_id",
            unique=True,
            postgresql_where=text("job_id IS NULL"),
        ),
        Index(
            "uq_screening_configs_organization_id_job_id",
            "organization_id",
            "job_id",
            unique=True,
            postgresql_where=text("job_id IS NOT NULL"),
        ),
    )

    job_id: Mapped[UUID | None]
    weights: Mapped[dict[str, int]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    knockouts: Mapped[dict[str, bool]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    blind: Mapped[bool] = mapped_column(Boolean, server_default=true())
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    updated_by: Mapped[UUID | None]


class ScreeningResult(IdMixin, TenantMixin, Base):
    """One application's screening (PRD §16): the match score, each factor with its evidence,
    and what's missing. Results are immutable; screening again with the same inputs reuses one
    (`cache_key`)."""

    __tablename__ = "screening_results"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "cache_key"),
        ForeignKeyConstraint(
            ["organization_id", "application_id"],
            ["applications.organization_id", "applications.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "job_id"], ["jobs.organization_id", "jobs.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["organization_id", "candidate_id"],
            ["candidates.organization_id", "candidates.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("score BETWEEN 0 AND 100", name="score"),
    )

    application_id: Mapped[UUID] = mapped_column(index=True)
    job_id: Mapped[UUID]
    candidate_id: Mapped[UUID]
    cache_key: Mapped[str] = mapped_column(Text)
    job_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    config_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    prompt_version: Mapped[str] = mapped_column(Text, server_default="")
    model: Mapped[str] = mapped_column(Text, server_default="")
    # Whether the AI read a blind resume (no name or personal details); null for results made
    # before this was recorded.
    blind: Mapped[bool | None] = mapped_column(Boolean)
    score: Mapped[int] = mapped_column(Integer)
    factors: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    skill_match: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    experience: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    strengths: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    concerns: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    missing: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    knockouts: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    semantic_similarity: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ApplicationHistory(IdMixin, TenantMixin, Base):
    """Every change to an application's stage or assignment (PRD §18: overrides audited), with
    the score and rank it had at the time."""

    __tablename__ = "application_history"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "application_id"],
            ["applications.organization_id", "applications.id"],
            ondelete="CASCADE",
        ),
    )

    application_id: Mapped[UUID] = mapped_column(index=True)
    from_stage: Mapped[str | None] = mapped_column(Text)
    to_stage: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    score: Mapped[int | None] = mapped_column(Integer)
    rank: Mapped[int | None] = mapped_column(Integer)
    override: Mapped[bool] = mapped_column(Boolean, server_default=false())
    actor_id: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
