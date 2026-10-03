"""Screening: configurations (an organisation default and per-job overrides), results and the
history of each application's stage; applications gain their own recruiter, hiring manager and
latest screening result (SP-05).

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-03
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from hirevion_core.db.rls import grant_sql, tenant_policy_sql

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created() -> sa.Column[datetime]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


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


def _jsonb(name: str, default: str) -> sa.Column[object]:
    return sa.Column(
        name, postgresql.JSONB(), server_default=sa.text(f"'{default}'::jsonb"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "screening_configs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        _jsonb("weights", "{}"),
        _jsonb("knockouts", "{}"),
        sa.Column("blind", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        _created(),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        _organization_fk("screening_configs"),
        _composite_fk("screening_configs", "job_id", "jobs", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_screening_configs")),
    )
    op.create_index(
        "uq_screening_configs_organization_default",
        "screening_configs",
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text("job_id IS NULL"),
    )
    op.create_index(
        "uq_screening_configs_organization_id_job_id",
        "screening_configs",
        ["organization_id", "job_id"],
        unique=True,
        postgresql_where=sa.text("job_id IS NOT NULL"),
    )
    _tenant("screening_configs", ["SELECT", "INSERT", "UPDATE"])

    op.create_table(
        "screening_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("cache_key", sa.Text(), nullable=False),
        sa.Column("job_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("config_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("prompt_version", sa.Text(), server_default="", nullable=False),
        sa.Column("model", sa.Text(), server_default="", nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        _jsonb("factors", "{}"),
        _jsonb("skill_match", "{}"),
        _jsonb("experience", "{}"),
        _jsonb("strengths", "[]"),
        _jsonb("concerns", "[]"),
        _jsonb("missing", "[]"),
        _jsonb("knockouts", "[]"),
        sa.Column("semantic_similarity", sa.Float(), nullable=True),
        _created(),
        sa.CheckConstraint("score BETWEEN 0 AND 100", name=op.f("ck_screening_results_score")),
        _organization_fk("screening_results"),
        _composite_fk("screening_results", "application_id", "applications", ondelete="CASCADE"),
        _composite_fk("screening_results", "job_id", "jobs", ondelete="CASCADE"),
        _composite_fk("screening_results", "candidate_id", "candidates", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_screening_results")),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_screening_results_organization_id_id")
        ),
        sa.UniqueConstraint(
            "organization_id",
            "cache_key",
            name=op.f("uq_screening_results_organization_id_cache_key"),
        ),
    )
    op.create_index(
        op.f("ix_screening_results_application_id"), "screening_results", ["application_id"]
    )
    _tenant("screening_results", ["SELECT", "INSERT"])

    op.create_table(
        "application_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("from_stage", sa.Text(), nullable=True),
        sa.Column("to_stage", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("override", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        _created(),
        _organization_fk("application_history"),
        _composite_fk("application_history", "application_id", "applications", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_application_history")),
    )
    op.create_index(
        op.f("ix_application_history_application_id"), "application_history", ["application_id"]
    )
    _tenant("application_history", ["SELECT", "INSERT"])

    for column in ("recruiter_id", "hiring_manager_id", "screening_result_id"):
        op.add_column("applications", sa.Column(column, sa.Uuid(), nullable=True))
    for column in ("recruiter_id", "hiring_manager_id"):
        op.create_foreign_key(
            op.f(f"fk_applications_organization_id_{column}_users"),
            "applications",
            "users",
            ["organization_id", column],
            ["organization_id", "id"],
        )
    op.create_foreign_key(
        op.f("fk_applications_organization_id_screening_result_id_screening_results"),
        "applications",
        "screening_results",
        ["organization_id", "screening_result_id"],
        ["organization_id", "id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_applications_organization_id_screening_result_id_screening_results"),
        "applications",
        type_="foreignkey",
    )
    for column in ("recruiter_id", "hiring_manager_id"):
        op.drop_constraint(
            op.f(f"fk_applications_organization_id_{column}_users"),
            "applications",
            type_="foreignkey",
        )
    for column in ("screening_result_id", "hiring_manager_id", "recruiter_id"):
        op.drop_column("applications", column)
    op.drop_table("application_history")
    op.drop_table("screening_results")
    op.drop_table("screening_configs")
