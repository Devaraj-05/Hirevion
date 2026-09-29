"""Audit log: monthly partitions, per-organisation hash chain, append-only.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from hirevion_core.db.rls import grant_sql, tenant_policy_sql

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("resource_type", sa.Text(), nullable=False),
        sa.Column("resource_id", sa.Text(), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("prev_hash", sa.LargeBinary(), nullable=False),
        sa.Column("hash", sa.LargeBinary(), nullable=False),
        sa.CheckConstraint("seq >= 1", name=op.f("ck_audit_logs_seq_positive")),
        sa.CheckConstraint(
            "octet_length(hash) = 32 AND octet_length(prev_hash) = 32",
            name=op.f("ck_audit_logs_hash_length"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_audit_logs_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", "occurred_at", name=op.f("pk_audit_logs")),
        postgresql_partition_by="RANGE (occurred_at)",
    )
    op.create_index(
        op.f("ix_audit_logs_organization_id_seq"), "audit_logs", ["organization_id", "seq"]
    )
    # Monthly partitions are created by `hv migrate`; anything outside them lands here.
    op.execute("CREATE TABLE audit_logs_default PARTITION OF audit_logs DEFAULT")

    for statement in tenant_policy_sql("audit_logs"):
        op.execute(statement)
    # Append-only: the app role may read and add entries, never change or remove them.
    op.execute(grant_sql("audit_logs", ["SELECT", "INSERT"]))
    # The trigger also stops the admin role. Retention drops whole partitions (SP-22), which
    # fires no row trigger.
    op.execute(
        """
        CREATE FUNCTION audit_logs_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_logs is append-only' USING ERRCODE = 'insufficient_privilege';
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER audit_logs_append_only BEFORE UPDATE OR DELETE ON audit_logs "
        "FOR EACH ROW EXECUTE FUNCTION audit_logs_append_only()"
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.execute("DROP FUNCTION audit_logs_append_only()")
