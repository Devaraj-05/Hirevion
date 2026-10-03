from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hirevion_core.db.base import Base, IdMixin, TenantMixin, TimestampMixin
from hirevion_core.models.job import EMBEDDING_DIMENSIONS

# PRD §18's screening stages; SP-04b sets `parsed`, SP-05 the rest.
APPLICATION_STAGES = (
    "uploaded",
    "parsed",
    "screened",
    "ranked",
    "review",
    "shortlisted",
    "rejected",
    "on_hold",
)
APPLICATION_SOURCES = ("upload",)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Candidate(IdMixin, TenantMixin, TimestampMixin, Base):
    """A person, once per organisation however many resumes arrive (PRD §19). `profile` is the
    latest verified parse, with evidence; Aadhaar and PAN never reach it unmasked."""

    __tablename__ = "candidates"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "resume_document_id"],
            ["documents.organization_id", "documents.id"],
            use_alter=True,
        ),
        Index(
            "uq_candidates_organization_id_email",
            "organization_id",
            "email",
            unique=True,
            postgresql_where=text("email IS NOT NULL"),
        ),
        Index("ix_candidates_organization_id_phone", "organization_id", "phone"),
        Index(
            "ix_candidates_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )

    name: Mapped[str] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(CITEXT)
    phone: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    headline: Mapped[str | None] = mapped_column(Text)
    profile: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    flags: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    resume_document_id: Mapped[UUID | None]
    created_by: Mapped[UUID | None]


class CandidateSkill(Base):
    """A skill from a candidate's resume, linked to the taxonomy when it's known there."""

    __tablename__ = "candidate_skills"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "candidate_id"],
            ["candidates.organization_id", "candidates.id"],
            ondelete="CASCADE",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    candidate_id: Mapped[UUID] = mapped_column(primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    skill_id: Mapped[UUID | None] = mapped_column(ForeignKey("skills.id"))
    years: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))


class Application(IdMixin, TenantMixin, TimestampMixin, Base):
    """A candidate for a job, from the resume uploaded to it; screening (SP-05) moves its stage."""

    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "job_id", "candidate_id"),
        ForeignKeyConstraint(
            ["organization_id", "candidate_id"],
            ["candidates.organization_id", "candidates.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "job_id"], ["jobs.organization_id", "jobs.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["organization_id", "document_id"], ["documents.organization_id", "documents.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "recruiter_id"], ["users.organization_id", "users.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "hiring_manager_id"], ["users.organization_id", "users.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "screening_result_id"],
            ["screening_results.organization_id", "screening_results.id"],
            use_alter=True,
        ),
        Index("ix_applications_job_id_rank", "job_id", "rank"),
        CheckConstraint(_in("stage", APPLICATION_STAGES), name="stage"),
        CheckConstraint(_in("source", APPLICATION_SOURCES), name="source"),
    )

    candidate_id: Mapped[UUID] = mapped_column(index=True)
    job_id: Mapped[UUID]
    document_id: Mapped[UUID | None]
    stage: Mapped[str] = mapped_column(Text, server_default="uploaded")
    source: Mapped[str] = mapped_column(Text, server_default="upload")
    # Who looks after this candidate for this job; the job's recruiter and manager when unset.
    recruiter_id: Mapped[UUID | None]
    hiring_manager_id: Mapped[UUID | None]
    screening_result_id: Mapped[UUID | None]
    # Place in the job's ranking (1 is best); null until screened.
    rank: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[UUID | None]
