"""AI invocation records (PRD §79) and per-organisation quotas.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from hirevion_core.db.rls import grant_sql, tenant_policy_sql

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _zero() -> sa.TextClause:
    return sa.text("0")


def upgrade() -> None:
    op.create_table(
        "ai_invocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("service", sa.Text(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("model_version", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column("rubric_version", sa.Text(), nullable=True),
        sa.Column("evaluation_version", sa.Text(), nullable=True),
        sa.Column(
            "input_refs", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("output", postgresql.JSONB(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), server_default=_zero(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default=_zero(), nullable=False),
        sa.Column("audio_seconds", sa.Numeric(), server_default=_zero(), nullable=False),
        sa.Column("characters", sa.Integer(), server_default=_zero(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "service IN ('llm', 'embedding', 'stt', 'tts', 'vision', 'ocr')",
            name=op.f("ck_ai_invocations_service"),
        ),
        sa.CheckConstraint("status IN ('ok', 'error')", name=op.f("ck_ai_invocations_status")),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_ai_invocations_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", "occurred_at", name=op.f("pk_ai_invocations")),
        postgresql_partition_by="RANGE (occurred_at)",
    )
    op.create_index(
        "ix_ai_invocations_organization_id_occurred_at",
        "ai_invocations",
        ["organization_id", "occurred_at"],
    )
    op.execute("CREATE TABLE ai_invocations_default PARTITION OF ai_invocations DEFAULT")
    for statement in tenant_policy_sql("ai_invocations"):
        op.execute(statement)
    # A record of spend: the app adds rows and reads them, never changes them.
    op.execute(grant_sql("ai_invocations", ["SELECT", "INSERT"]))

    op.create_table(
        "quotas",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("meter", sa.Text(), nullable=False),
        sa.Column("period", sa.Text(), nullable=False),
        sa.Column("limit_value", sa.Numeric(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("period IN ('month')", name=op.f("ck_quotas_period")),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_quotas_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("organization_id", "meter", "period", name=op.f("pk_quotas")),
    )
    for statement in tenant_policy_sql("quotas"):
        op.execute(statement)
    # Quotas are set by platform administration (SP-22); tenants only read theirs.
    op.execute(grant_sql("quotas", ["SELECT"]))


def downgrade() -> None:
    op.drop_table("quotas")
    op.drop_table("ai_invocations")
