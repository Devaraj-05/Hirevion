"""Coding answers (SP-16; PRD §45, §47, §48; ADR-0033).

- `coding_submissions`: every submission of a coding question (the code, its language label, size
  and SHA-256, and whether the candidate submitted it or the question's end kept the last saved
  text). The latest is the question's final code. Nothing is executed.
- `coding_telemetry`: the coding console's integrity events (typing started and stopped, paste,
  copy, cut, focus, blur) with the clipboard length only; never the text, never keystrokes.

Both are tenant-scoped and insert-only.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-23
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op

from hirevion_core.db.rls import grant_sql, tenant_policy_sql

revision: str = "0022"
down_revision: str | Sequence[str] | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LANGUAGES = ("python", "javascript", "typescript", "sql")
SOURCES = ("submitted", "time_limit", "closed")
KINDS = ("typing_started", "typing_stopped", "paste", "copy", "cut", "focus", "blur")
CLIPBOARD = ("paste", "copy", "cut")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _ts(name: str, default: str) -> sa.Column[datetime]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text(default), nullable=False
    )


def _fks(table: str) -> list[sa.ForeignKeyConstraint]:
    return [
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f(f"fk_{table}_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "interview_id"],
            ["interviews.organization_id", "interviews.id"],
            name=op.f(f"fk_{table}_organization_id_interview_id_interviews"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "question_id"],
            ["interview_questions.organization_id", "interview_questions.id"],
            name=op.f(f"fk_{table}_organization_id_question_id_interview_questions"),
            ondelete="CASCADE",
        ),
    ]


def _tenant(table: str, privileges: list[str]) -> None:
    op.create_index(op.f(f"ix_{table}_organization_id"), table, ["organization_id"])
    for statement in tenant_policy_sql(table):
        op.execute(statement)
    op.execute(grant_sql(table, privileges))


def upgrade() -> None:
    op.create_table(
        "coding_submissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        _ts("created_at", "clock_timestamp()"),
        sa.CheckConstraint(_in("language", LANGUAGES), name=op.f("ck_coding_submissions_language")),
        sa.CheckConstraint(_in("source", SOURCES), name=op.f("ck_coding_submissions_source")),
        sa.CheckConstraint("size >= 0", name=op.f("ck_coding_submissions_size")),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_coding_submissions_sha256")),
        *_fks("coding_submissions"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_coding_submissions")),
    )
    op.create_index(
        "ix_coding_submissions_interview_id",
        "coding_submissions",
        ["interview_id", "created_at"],
    )
    _tenant("coding_submissions", ["SELECT", "INSERT"])

    op.create_table(
        "coding_telemetry",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("chars", sa.Integer(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        _ts("received_at", "now()"),
        sa.CheckConstraint(_in("kind", KINDS), name=op.f("ck_coding_telemetry_kind")),
        sa.CheckConstraint(
            f"({_in('kind', CLIPBOARD)} AND chars IS NOT NULL AND chars >= 0) OR "
            f"(NOT {_in('kind', CLIPBOARD)} AND chars IS NULL)",
            name=op.f("ck_coding_telemetry_chars"),
        ),
        *_fks("coding_telemetry"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_coding_telemetry")),
    )
    op.create_index(
        "ix_coding_telemetry_interview_id", "coding_telemetry", ["interview_id", "occurred_at"]
    )
    _tenant("coding_telemetry", ["SELECT", "INSERT"])


def downgrade() -> None:
    op.drop_table("coding_telemetry")
    op.drop_table("coding_submissions")
