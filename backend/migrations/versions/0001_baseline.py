"""Baseline: extensions, organizations and feature flags.

Revision ID: 0001
Revises:
Create Date: 2026-09-29
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from hirevion_core.db.rls import CURRENT_ORG, grant_sql, tenant_policy_sql
from hirevion_core.settings import APP_ROLE

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXTENSIONS = ("vector", "pg_trgm", "citext")


def _timestamps() -> list[sa.Column[datetime]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    for extension in EXTENSIONS:
        op.execute(f"CREATE EXTENSION IF NOT EXISTS {extension}")

    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", postgresql.CITEXT(), nullable=False),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('active', 'suspended')", name=op.f("ck_organizations_status")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
        sa.UniqueConstraint("slug", name=op.f("uq_organizations_slug")),
    )
    for statement in tenant_policy_sql("organizations", column="id"):
        op.execute(statement)
    # Creating an organisation is a platform action (SP-02, SP-22), never a tenant one.
    op.execute(grant_sql("organizations", ["SELECT", "UPDATE"]))

    op.create_table(
        "feature_flags",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "rollout_percent", sa.SmallInteger(), server_default=sa.text("100"), nullable=False
        ),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "rollout_percent BETWEEN 0 AND 100", name=op.f("ck_feature_flags_rollout_percent")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_feature_flags_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feature_flags")),
        sa.UniqueConstraint(
            "key",
            "organization_id",
            name=op.f("uq_feature_flags_key_organization_id"),
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(op.f("ix_feature_flags_organization_id"), "feature_flags", ["organization_id"])
    # Tenants read the global flags and their own overrides, and change neither.
    op.execute("ALTER TABLE feature_flags ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE feature_flags FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY feature_flags_read ON feature_flags FOR SELECT TO {APP_ROLE} "
        f"USING (organization_id IS NULL OR organization_id = {CURRENT_ORG})"
    )
    op.execute(grant_sql("feature_flags", ["SELECT"]))


def downgrade() -> None:
    op.drop_table("feature_flags")
    op.drop_table("organizations")
