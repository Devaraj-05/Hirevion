"""Jobs and documents: the shared skills taxonomy, jobs and their skills and versions, and
documents (SP-04a, ADR-0015).

The taxonomy has no `organization_id`: every organisation reads the same skills, and only
migrations change them, so the application role may only read it.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-02
"""

from collections.abc import Sequence
from datetime import datetime
from importlib.resources import files

import sqlalchemy as sa
import yaml
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from hirevion_core.db.rls import grant_sql, tenant_policy_sql
from hirevion_core.ids import uuid7

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SKILLS_FILE = files("hirevion_core.jobs") / "data" / "skills.yaml"


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


def _seed_skills() -> None:
    rows = yaml.safe_load(SKILLS_FILE.read_text(encoding="utf-8"))
    skills = sa.table(
        "skills", sa.column("id", sa.Uuid()), sa.column("name"), sa.column("category")
    )
    aliases = sa.table("skill_aliases", sa.column("alias"), sa.column("skill_id", sa.Uuid()))
    skill_rows, alias_rows = [], []
    for name, category, names in rows:
        skill_id = uuid7()
        skill_rows.append({"id": skill_id, "name": name, "category": category})
        alias_rows.extend({"alias": alias, "skill_id": skill_id} for alias in names)
    op.bulk_insert(skills, skill_rows)
    op.bulk_insert(aliases, alias_rows)


def upgrade() -> None:
    # The shared taxonomy.
    op.create_table(
        "skills",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", postgresql.CITEXT(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_skills")),
        sa.UniqueConstraint("name", name=op.f("uq_skills_name")),
    )
    op.create_table(
        "skill_aliases",
        sa.Column("alias", postgresql.CITEXT(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["skills.id"],
            name=op.f("fk_skill_aliases_skill_id_skills"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("alias", name=op.f("pk_skill_aliases")),
    )
    op.create_index(op.f("ix_skill_aliases_skill_id"), "skill_aliases", ["skill_id"])
    for table in ("skills", "skill_aliases"):
        op.execute(grant_sql(table, ["SELECT"]))
    _seed_skills()

    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("department_id", sa.Uuid(), nullable=True),
        sa.Column("team_id", sa.Uuid(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("work_model", sa.Text(), nullable=True),
        sa.Column("employment_type", sa.Text(), server_default="full_time", nullable=False),
        sa.Column("experience_min", sa.Numeric(4, 1), nullable=True),
        sa.Column("experience_max", sa.Numeric(4, 1), nullable=True),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "responsibilities",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "qualifications",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "domain",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("salary_min", sa.Numeric(14, 2), nullable=True),
        sa.Column("salary_max", sa.Numeric(14, 2), nullable=True),
        sa.Column("salary_currency", sa.Text(), nullable=True),
        sa.Column("recruiter_id", sa.Uuid(), nullable=True),
        sa.Column("hiring_manager_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.Text(), server_default="draft", nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("jd_document_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            _in("status", ("draft", "open", "paused", "closed", "archived")),
            name=op.f("ck_jobs_status"),
        ),
        sa.CheckConstraint(
            f"work_model IS NULL OR {_in('work_model', ('onsite', 'hybrid', 'remote'))}",
            name=op.f("ck_jobs_work_model"),
        ),
        sa.CheckConstraint(
            _in(
                "employment_type",
                ("full_time", "part_time", "contract", "internship", "temporary"),
            ),
            name=op.f("ck_jobs_employment_type"),
        ),
        sa.CheckConstraint(
            "experience_min IS NULL OR experience_max IS NULL OR experience_min <= experience_max",
            name=op.f("ck_jobs_experience_range"),
        ),
        sa.CheckConstraint(
            "salary_min IS NULL OR salary_max IS NULL OR salary_min <= salary_max",
            name=op.f("ck_jobs_salary_range"),
        ),
        _organization_fk("jobs"),
        _composite_fk("jobs", "department_id", "departments"),
        _composite_fk("jobs", "team_id", "teams"),
        sa.ForeignKeyConstraint(
            ["organization_id", "recruiter_id"],
            ["users.organization_id", "users.id"],
            name=op.f("fk_jobs_organization_id_recruiter_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "hiring_manager_id"],
            ["users.organization_id", "users.id"],
            name=op.f("fk_jobs_organization_id_hiring_manager_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_jobs_organization_id_id")),
        sa.UniqueConstraint(
            "organization_id", "number", name=op.f("uq_jobs_organization_id_number")
        ),
    )
    _tenant("jobs", ["SELECT", "INSERT", "UPDATE"])

    op.create_table(
        "job_skills",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=True),
        sa.Column("importance", sa.Text(), nullable=False),
        sa.Column("min_years", sa.Numeric(4, 1), nullable=True),
        sa.CheckConstraint(
            _in("importance", ("required", "preferred", "optional")),
            name=op.f("ck_job_skills_importance"),
        ),
        _organization_fk("job_skills"),
        _composite_fk("job_skills", "job_id", "jobs", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["skill_id"], ["skills.id"], name=op.f("fk_job_skills_skill_id_skills")
        ),
        sa.PrimaryKeyConstraint("job_id", "position", name=op.f("pk_job_skills")),
    )
    _tenant("job_skills", ["SELECT", "INSERT", "DELETE"])

    op.create_table(
        "job_versions",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        _organization_fk("job_versions"),
        _composite_fk("job_versions", "job_id", "jobs", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("job_id", "version", name=op.f("pk_job_versions")),
    )
    _tenant("job_versions", ["SELECT", "INSERT"])

    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("filename", sa.Text(), nullable=True),
        sa.Column("content_type", sa.Text(), nullable=True),
        sa.Column("size", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=True),
        sa.Column("blob_path", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="uploaded", nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("pages", sa.Integer(), nullable=True),
        sa.Column(
            "flags", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("extraction", postgresql.JSONB(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(_in("kind", ("jd", "resume")), name=op.f("ck_documents_kind")),
        sa.CheckConstraint(
            _in(
                "status",
                (
                    "uploaded",
                    "scanning",
                    "extracting",
                    "parsing",
                    "parsed",
                    "quarantined",
                    "failed",
                ),
            ),
            name=op.f("ck_documents_status"),
        ),
        _organization_fk("documents"),
        _composite_fk("documents", "job_id", "jobs", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
    )
    op.create_index("ix_documents_job_id_created_at", "documents", ["job_id", "created_at"])
    _tenant("documents", ["SELECT", "INSERT", "UPDATE"])


def downgrade() -> None:
    op.drop_table("documents")
    op.drop_table("job_versions")
    op.drop_table("job_skills")
    op.drop_table("jobs")
    op.drop_table("skill_aliases")
    op.drop_table("skills")
