from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hirevion_core.db.base import Base, IdMixin, TenantMixin, TimestampMixin

JOB_STATUSES = ("draft", "open", "paused", "closed", "archived")
WORK_MODELS = ("onsite", "hybrid", "remote")
EMPLOYMENT_TYPES = ("full_time", "part_time", "contract", "internship", "temporary")
SKILL_IMPORTANCE = ("required", "preferred", "optional")
EMBEDDING_DIMENSIONS = 1536


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Job(IdMixin, TenantMixin, TimestampMixin, Base):
    """A job (PRD §11). Its number is shown as JOB-0042. Every change writes a `job_versions`
    snapshot. It belongs to a team and a recruiter, which the resource scope filters on."""

    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "number"),
        ForeignKeyConstraint(
            ["organization_id", "department_id"],
            ["departments.organization_id", "departments.id"],
        ),
        ForeignKeyConstraint(["organization_id", "team_id"], ["teams.organization_id", "teams.id"]),
        ForeignKeyConstraint(
            ["organization_id", "recruiter_id"], ["users.organization_id", "users.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "hiring_manager_id"], ["users.organization_id", "users.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "interview_template_id"],
            ["interview_templates.organization_id", "interview_templates.id"],
        ),
        CheckConstraint(_in("status", JOB_STATUSES), name="status"),
        CheckConstraint(
            f"work_model IS NULL OR {_in('work_model', WORK_MODELS)}", name="work_model"
        ),
        CheckConstraint(_in("employment_type", EMPLOYMENT_TYPES), name="employment_type"),
        CheckConstraint(
            "experience_min IS NULL OR experience_max IS NULL OR experience_min <= experience_max",
            name="experience_range",
        ),
        CheckConstraint(
            "salary_min IS NULL OR salary_max IS NULL OR salary_min <= salary_max",
            name="salary_range",
        ),
    )

    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    department_id: Mapped[UUID | None]
    team_id: Mapped[UUID | None]
    location: Mapped[str | None] = mapped_column(Text)
    work_model: Mapped[str | None] = mapped_column(Text)
    employment_type: Mapped[str] = mapped_column(Text, server_default="full_time")
    experience_min: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    experience_max: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    description: Mapped[str] = mapped_column(Text, server_default="")
    responsibilities: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]")
    )
    qualifications: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]")
    )
    domain: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    salary_min: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    salary_max: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    salary_currency: Mapped[str | None] = mapped_column(Text)
    recruiter_id: Mapped[UUID | None]
    hiring_manager_id: Mapped[UUID | None]
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    jd_document_id: Mapped[UUID | None]
    # PRD §11's "Interview Template": what new interviews for this job use by default (SP-07a).
    interview_template_id: Mapped[UUID | None]
    created_by: Mapped[UUID | None]


class JobSkill(Base):
    """A skill a job asks for: required, preferred or optional (PRD §17), linked to the taxonomy
    when the skill is known there."""

    __tablename__ = "job_skills"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "job_id"], ["jobs.organization_id", "jobs.id"], ondelete="CASCADE"
        ),
        CheckConstraint(_in("importance", SKILL_IMPORTANCE), name="importance"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    job_id: Mapped[UUID] = mapped_column(primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    skill_id: Mapped[UUID | None] = mapped_column(ForeignKey("skills.id"))
    importance: Mapped[str] = mapped_column(Text)
    min_years: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))


class JobVersion(Base):
    """A snapshot of a job after a change: the job's fields and skills, and why it changed."""

    __tablename__ = "job_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "job_id"], ["jobs.organization_id", "jobs.id"], ondelete="CASCADE"
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    job_id: Mapped[UUID] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
