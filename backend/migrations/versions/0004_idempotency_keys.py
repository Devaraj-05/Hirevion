"""Idempotency keys for create requests.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from hirevion_core.db.rls import grant_sql, tenant_policy_sql
from hirevion_core.settings import APP_ROLE

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.LargeBinary(), nullable=False),
        sa.Column("status_code", sa.SmallInteger(), nullable=True),
        sa.Column("response", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_idempotency_keys_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "scope", "key", name=op.f("pk_idempotency_keys")
        ),
    )
    op.create_index("ix_idempotency_keys_created_at", "idempotency_keys", ["created_at"])
    for statement in tenant_policy_sql("idempotency_keys"):
        op.execute(statement)
    # The app claims keys and records responses; expired keys are purged by the admin role.
    op.execute(grant_sql("idempotency_keys", ["SELECT", "INSERT"]))
    op.execute(f"GRANT UPDATE (status_code, response) ON idempotency_keys TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("idempotency_keys")
