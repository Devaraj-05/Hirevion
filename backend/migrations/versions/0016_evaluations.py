"""Evaluations (SP-10; PRD §44, §70, §79): an evaluation per run with the versions it pinned, each
question's eight scores with their evidence, and the reviewers' own scores for calibration.
`ai_invocations` already holds the §79 fields, so it is not changed.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-10
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from hirevion_core.db.rls import grant_sql, tenant_policy_sql

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KINDS = ("initial", "rerun")
STATUSES = ("running", "ready", "failed")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _created() -> sa.Column[datetime]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def _timestamps() -> list[sa.Column[datetime]]:
    return [
        _created(),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _ts(name: str) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=True)


def _jsonb(name: str, default: str) -> sa.Column[object]:
    return sa.Column(
        name, postgresql.JSONB(), server_default=sa.text(f"'{default}'::jsonb"), nullable=False
    )


def _texts(name: str) -> sa.Column[object]:
    return sa.Column(
        name, postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False
    )


def _organization_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id"],
        ["organizations.id"],
        name=op.f(f"fk_{table}_organization_id_organizations"),
    )


def _composite_fk(
    table: str, column: str, target: str, ondelete: str | None = "CASCADE"
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


def upgrade() -> None:
    op.create_table(
        "evaluations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), server_default="initial", nullable=False),
        sa.Column("rerun_of", sa.Uuid(), nullable=True),
        sa.Column("status", sa.Text(), server_default="running", nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("rubric_version", sa.Text(), nullable=False),
        sa.Column("evaluation_version", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=True),
        _jsonb("pinned", "{}"),
        sa.Column("overall_score", sa.Numeric(4, 2), nullable=True),
        sa.Column("communication_score", sa.Numeric(4, 2), nullable=True),
        _jsonb("skills", "[]"),
        _jsonb("summary", "{}"),
        _texts("flags"),
        sa.Column("diff", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        _ts("completed_at"),
        *_timestamps(),
        sa.CheckConstraint(_in("kind", KINDS), name=op.f("ck_evaluations_kind")),
        sa.CheckConstraint(_in("status", STATUSES), name=op.f("ck_evaluations_status")),
        _organization_fk("evaluations"),
        _composite_fk("evaluations", "interview_id", "interviews"),
        _composite_fk("evaluations", "rerun_of", "evaluations"),
        sa.ForeignKeyConstraint(
            ["organization_id", "created_by"],
            ["users.organization_id", "users.id"],
            name=op.f("fk_evaluations_organization_id_created_by_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluations")),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_evaluations_organization_id_id")
        ),
        sa.UniqueConstraint(
            "interview_id", "sequence", name=op.f("uq_evaluations_interview_id_sequence")
        ),
    )
    op.create_index(
        "uq_evaluations_initial_per_interview",
        "evaluations",
        ["interview_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'initial' AND status IN ('running', 'ready')"),
    )
    _tenant("evaluations", ["SELECT", "INSERT", "UPDATE"])

    op.create_table(
        "question_evaluations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("evaluation_id", sa.Uuid(), nullable=False),
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("skill", sa.Text(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("weight", sa.Numeric(3, 1), nullable=False),
        _jsonb("dimensions", "{}"),
        sa.Column("overall_score", sa.Numeric(4, 2), nullable=False),
        _texts("unsupported"),
        _texts("missing_concepts"),
        sa.Column("note", sa.Text(), server_default="", nullable=False),
        _texts("flags"),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("input_digest", sa.Text(), nullable=False),
        _created(),
        _organization_fk("question_evaluations"),
        _composite_fk("question_evaluations", "evaluation_id", "evaluations"),
        _composite_fk("question_evaluations", "question_id", "interview_questions"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_question_evaluations")),
        sa.UniqueConstraint(
            "evaluation_id",
            "question_id",
            name=op.f("uq_question_evaluations_evaluation_id_question_id"),
        ),
    )
    op.create_index(
        "ix_question_evaluations_interview_id", "question_evaluations", ["interview_id"]
    )
    # Written once with the evaluation and never changed.
    _tenant("question_evaluations", ["SELECT", "INSERT"])

    op.create_table(
        "human_scores",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=False),
        _jsonb("dimensions", "{}"),
        sa.Column("note", sa.Text(), server_default="", nullable=False),
        *_timestamps(),
        _organization_fk("human_scores"),
        _composite_fk("human_scores", "interview_id", "interviews"),
        _composite_fk("human_scores", "question_id", "interview_questions"),
        sa.ForeignKeyConstraint(
            ["organization_id", "reviewer_id"],
            ["users.organization_id", "users.id"],
            name=op.f("fk_human_scores_organization_id_reviewer_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_human_scores")),
        sa.UniqueConstraint(
            "question_id", "reviewer_id", name=op.f("uq_human_scores_question_id_reviewer_id")
        ),
    )
    op.create_index("ix_human_scores_interview_id", "human_scores", ["interview_id"])
    _tenant("human_scores", ["SELECT", "INSERT", "UPDATE"])


def downgrade() -> None:
    op.drop_table("human_scores")
    op.drop_table("question_evaluations")
    op.drop_table("evaluations")
