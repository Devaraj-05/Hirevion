"""Candidates: candidates, their skills and their applications to jobs; documents gain the
candidate and archive they belong to, the `archive` kind and the `ocr` status (SP-04b,
ADR-0015).

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-03
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from hirevion_core.db.rls import grant_sql, tenant_policy_sql

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = ("jd", "resume")
KINDS = ("jd", "resume", "archive")
OLD_STATUSES = ("uploaded", "scanning", "extracting", "parsing", "parsed", "quarantined", "failed")
STATUSES = (
    "uploaded",
    "scanning",
    "extracting",
    "ocr",
    "parsing",
    "parsed",
    "quarantined",
    "failed",
)
STAGES = (
    "uploaded",
    "parsed",
    "screened",
    "ranked",
    "review",
    "shortlisted",
    "rejected",
    "on_hold",
)


def _timestamps() -> list[sa.Column[datetime]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _organization_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id"],
        ["organizations.id"],
        name=op.f(f"fk_{table}_organization_id_organizations"),
    )


def _composite_fk(
    table: str, column: str, target: str, ondelete: str | None = None
) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id", column],
        [f"{target}.organization_id", f"{target}.id"],
        name=op.f(f"fk_{table}_organization_id_{column}_{target}"),
        ondelete=ondelete,
    )


def _tenant(table: str, privileges: list[str]) -> None:
    op.create_index(op.f(f"ix_{table}_organization_id"), table, ["organization_id"])
    for statement in tenant_policy_sql(table):
        op.execute(statement)
    op.execute(grant_sql(table, privileges))


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _document_checks(kinds: tuple[str, ...], statuses: tuple[str, ...]) -> None:
    op.drop_constraint(op.f("ck_documents_kind"), "documents", type_="check")
    op.drop_constraint(op.f("ck_documents_status"), "documents", type_="check")
    op.create_check_constraint(op.f("ck_documents_kind"), "documents", _in("kind", kinds))
    op.create_check_constraint(op.f("ck_documents_status"), "documents", _in("status", statuses))


def upgrade() -> None:
    op.create_table(
        "candidates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("headline", sa.Text(), nullable=True),
        sa.Column(
            "profile", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "flags", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("resume_document_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        *_timestamps(),
        _organization_fk("candidates"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidates")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_candidates_organization_id_id")),
    )
    op.create_index(
        "uq_candidates_organization_id_email",
        "candidates",
        ["organization_id", "email"],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )
    op.create_index(
        "ix_candidates_organization_id_phone", "candidates", ["organization_id", "phone"]
    )
    op.create_index(
        "ix_candidates_name_trgm",
        "candidates",
        ["name"],
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    _tenant("candidates", ["SELECT", "INSERT", "UPDATE"])

    op.create_table(
        "candidate_skills",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=True),
        sa.Column("years", sa.Numeric(4, 1), nullable=True),
        _organization_fk("candidate_skills"),
        _composite_fk("candidate_skills", "candidate_id", "candidates", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["skill_id"], ["skills.id"], name=op.f("fk_candidate_skills_skill_id_skills")
        ),
        sa.PrimaryKeyConstraint("candidate_id", "position", name=op.f("pk_candidate_skills")),
    )
    _tenant("candidate_skills", ["SELECT", "INSERT", "DELETE"])

    # Documents: the candidate a resume became, the archive it came from, and the new values.
    op.create_unique_constraint(
        op.f("uq_documents_organization_id_id"), "documents", ["organization_id", "id"]
    )
    op.add_column("documents", sa.Column("candidate_id", sa.Uuid(), nullable=True))
    op.add_column("documents", sa.Column("parent_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_documents_organization_id_candidate_id_candidates"),
        "documents",
        "candidates",
        ["organization_id", "candidate_id"],
        ["organization_id", "id"],
    )
    op.create_foreign_key(
        op.f("fk_documents_organization_id_parent_id_documents"),
        "documents",
        "documents",
        ["organization_id", "parent_id"],
        ["organization_id", "id"],
    )
    op.create_index(
        "ix_documents_organization_id_sha256", "documents", ["organization_id", "sha256"]
    )
    op.create_index(op.f("ix_documents_candidate_id"), "documents", ["candidate_id"])
    op.create_index(op.f("ix_documents_parent_id"), "documents", ["parent_id"])
    _document_checks(KINDS, STATUSES)
    op.create_foreign_key(
        op.f("fk_candidates_organization_id_resume_document_id_documents"),
        "candidates",
        "documents",
        ["organization_id", "resume_document_id"],
        ["organization_id", "id"],
    )

    op.create_table(
        "applications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("stage", sa.Text(), server_default="uploaded", nullable=False),
        sa.Column("source", sa.Text(), server_default="upload", nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(_in("stage", STAGES), name=op.f("ck_applications_stage")),
        sa.CheckConstraint(_in("source", ("upload",)), name=op.f("ck_applications_source")),
        _organization_fk("applications"),
        _composite_fk("applications", "candidate_id", "candidates", ondelete="CASCADE"),
        _composite_fk("applications", "job_id", "jobs", ondelete="CASCADE"),
        _composite_fk("applications", "document_id", "documents"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_applications")),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_applications_organization_id_id")
        ),
        sa.UniqueConstraint(
            "organization_id",
            "job_id",
            "candidate_id",
            name=op.f("uq_applications_organization_id_job_id_candidate_id"),
        ),
    )
    op.create_index(op.f("ix_applications_candidate_id"), "applications", ["candidate_id"])
    _tenant("applications", ["SELECT", "INSERT", "UPDATE"])


def downgrade() -> None:
    op.drop_table("applications")
    op.drop_constraint(
        "fk_candidates_organization_id_resume_document_id_documents",
        "candidates",
        type_="foreignkey",
    )
    op.execute("DELETE FROM documents WHERE kind = 'archive'")
    op.execute("UPDATE documents SET status = 'extracting' WHERE status = 'ocr'")
    _document_checks(OLD_KINDS, OLD_STATUSES)
    op.drop_index("ix_documents_parent_id", "documents")
    op.drop_index("ix_documents_candidate_id", "documents")
    op.drop_index("ix_documents_organization_id_sha256", "documents")
    op.drop_column("documents", "parent_id")
    op.drop_column("documents", "candidate_id")
    op.drop_constraint(op.f("uq_documents_organization_id_id"), "documents", type_="unique")
    op.drop_table("candidate_skills")
    op.drop_table("candidates")
