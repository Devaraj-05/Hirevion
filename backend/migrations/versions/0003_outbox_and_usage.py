"""Transactional outbox and usage events.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from hirevion_core.db.rls import grant_sql, tenant_policy_sql
from hirevion_core.settings import RELAY_ROLE

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_outbox_events_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox_events")),
    )
    op.create_index(op.f("ix_outbox_events_organization_id"), "outbox_events", ["organization_id"])
    op.create_index(
        "ix_outbox_events_unpublished",
        "outbox_events",
        ["created_at"],
        postgresql_where=sa.text("published_at IS NULL"),
    )
    for statement in tenant_policy_sql("outbox_events"):
        op.execute(statement)
    op.execute(grant_sql("outbox_events", ["SELECT", "INSERT"]))
    # The relay publishes every organisation's events, and may only mark them published.
    op.execute(f"CREATE POLICY outbox_relay ON outbox_events TO {RELAY_ROLE} USING (true)")
    op.execute(grant_sql("outbox_events", ["SELECT", "DELETE"], role=RELAY_ROLE))
    op.execute(f"GRANT UPDATE (published_at, attempts) ON outbox_events TO {RELAY_ROLE}")

    op.create_table(
        "usage_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("meter", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "attributes",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint("quantity >= 0", name=op.f("ck_usage_events_quantity_non_negative")),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_usage_events_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", "occurred_at", name=op.f("pk_usage_events")),
        postgresql_partition_by="RANGE (occurred_at)",
    )
    op.create_index(
        op.f("ix_usage_events_organization_id_occurred_at"),
        "usage_events",
        ["organization_id", "occurred_at"],
    )
    op.execute("CREATE TABLE usage_events_default PARTITION OF usage_events DEFAULT")
    for statement in tenant_policy_sql("usage_events"):
        op.execute(statement)
    op.execute(grant_sql("usage_events", ["SELECT", "INSERT"]))


def downgrade() -> None:
    op.drop_table("usage_events")
    op.drop_table("outbox_events")
