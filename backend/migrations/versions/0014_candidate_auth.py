"""Candidate desktop sign-in and the desktop release registry (SP-07c): device keys, one-time
codes on a new device, rotating refresh-token families, the organisation's candidate-access
settings, and platform-wide releases and channels.

A refresh token and a code challenge arrive before their organisation is known, so two
SECURITY DEFINER lookups belong to `hirevion_auth`, as the other sign-in lookups do (0006, 0013).
Releases and channels are the same for every organisation: they have no `organization_id`, and
only the platform's own routes change them.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-09
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from hirevion_core.db.rls import grant_sql, tenant_policy_sql
from hirevion_core.settings import APP_ROLE, AUTH_ROLE

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REFRESH_LOOKUP_SQL = """
CREATE FUNCTION auth_candidate_refresh(p_token_hash bytea)
RETURNS TABLE (
    token_id uuid, organization_id uuid, account_id uuid, device_id uuid, family_id uuid,
    family_expires_at timestamptz, used_at timestamptz, revoked_at timestamptz
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
AS $$
    SELECT t.id, t.organization_id, t.account_id, t.device_id, t.family_id,
           t.family_expires_at, t.used_at, t.revoked_at
    FROM candidate_refresh_tokens t
    WHERE t.token_hash = p_token_hash
$$
"""

CHALLENGE_LOOKUP_SQL = """
CREATE FUNCTION auth_candidate_otp(p_challenge_id uuid)
RETURNS TABLE (organization_id uuid, account_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
AS $$
    SELECT c.organization_id, c.account_id FROM candidate_otps c WHERE c.id = p_challenge_id
$$
"""

FUNCTIONS = ("auth_candidate_refresh(bytea)", "auth_candidate_otp(uuid)")


def _created(name: str = "created_at") -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _ts(name: str, nullable: bool = True) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _organization_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id"],
        ["organizations.id"],
        name=op.f(f"fk_{table}_organization_id_organizations"),
    )


def _composite_fk(table: str, column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id", column],
        [f"{target}.organization_id", f"{target}.id"],
        name=op.f(f"fk_{table}_organization_id_{column}_{target}"),
        ondelete="CASCADE",
    )


def _tenant(table: str, privileges: list[str]) -> None:
    op.create_index(op.f(f"ix_{table}_organization_id"), table, ["organization_id"])
    for statement in tenant_policy_sql(table):
        op.execute(statement)
    op.execute(grant_sql(table, privileges))


def _jsonb(name: str, default: str = "{}") -> sa.Column[object]:
    return sa.Column(
        name, postgresql.JSONB(), server_default=sa.text(f"'{default}'::jsonb"), nullable=False
    )


def upgrade() -> None:
    op.add_column("organization_settings", _jsonb("candidate_access"))

    op.create_table(
        "candidate_devices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("jkt", sa.Text(), nullable=False),
        sa.Column("public_jwk", postgresql.JSONB(), nullable=False),
        sa.Column("name", sa.Text(), server_default="", nullable=False),
        _jsonb("app"),
        _ts("verified_at"),
        _created("first_seen_at"),
        _created("last_seen_at"),
        _ts("revoked_at"),
        _organization_fk("candidate_devices"),
        _composite_fk("candidate_devices", "account_id", "candidate_accounts"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_devices")),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_candidate_devices_organization_id_id")
        ),
        sa.UniqueConstraint("account_id", "jkt", name=op.f("uq_candidate_devices_account_id_jkt")),
    )
    _tenant("candidate_devices", ["SELECT", "INSERT", "UPDATE"])

    op.create_table(
        "candidate_otps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("jkt", sa.Text(), nullable=False),
        sa.Column("code_hash", sa.LargeBinary(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("sends", sa.Integer(), server_default=sa.text("1"), nullable=False),
        _ts("last_sent_at", nullable=False),
        _ts("expires_at", nullable=False),
        _ts("used_at"),
        _jsonb("context"),
        _created(),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_candidate_otps_attempts")),
        _organization_fk("candidate_otps"),
        _composite_fk("candidate_otps", "account_id", "candidate_accounts"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_otps")),
    )
    op.create_index("ix_candidate_otps_account_id", "candidate_otps", ["account_id"])
    _tenant("candidate_otps", ["SELECT", "INSERT", "UPDATE"])

    op.create_table(
        "candidate_refresh_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        _ts("family_expires_at", nullable=False),
        _created(),
        _ts("used_at"),
        _ts("revoked_at"),
        _organization_fk("candidate_refresh_tokens"),
        _composite_fk("candidate_refresh_tokens", "account_id", "candidate_accounts"),
        _composite_fk("candidate_refresh_tokens", "device_id", "candidate_devices"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_candidate_refresh_tokens_token_hash")),
    )
    op.create_index(
        "ix_candidate_refresh_tokens_family_id", "candidate_refresh_tokens", ["family_id"]
    )
    _tenant("candidate_refresh_tokens", ["SELECT", "INSERT", "UPDATE"])

    op.create_table(
        "desktop_releases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), server_default="stable", nullable=False),
        sa.Column("arch", sa.Text(), server_default="x64", nullable=False),
        sa.Column("notes", sa.Text(), server_default="", nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="draft", nullable=False),
        sa.Column("rollout_percent", sa.Integer(), server_default=sa.text("100"), nullable=False),
        _ts("published_at"),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        _created(),
        _created("updated_at"),
        sa.CheckConstraint(
            "channel IN ('stable', 'beta')", name=op.f("ck_desktop_releases_channel")
        ),
        sa.CheckConstraint("arch IN ('x64', 'arm64')", name=op.f("ck_desktop_releases_arch")),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'withdrawn')",
            name=op.f("ck_desktop_releases_status"),
        ),
        sa.CheckConstraint(
            "rollout_percent BETWEEN 0 AND 100", name=op.f("ck_desktop_releases_rollout_percent")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_desktop_releases")),
        sa.UniqueConstraint(
            "channel", "arch", "version", name=op.f("uq_desktop_releases_channel_arch_version")
        ),
    )
    op.execute(grant_sql("desktop_releases", ["SELECT", "INSERT", "UPDATE"]))

    op.create_table(
        "desktop_channels",
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("minimum_version", sa.Text(), server_default="0.0.0", nullable=False),
        sa.Column("download_url", sa.Text(), server_default="", nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        _created("updated_at"),
        sa.CheckConstraint(
            "channel IN ('stable', 'beta')", name=op.f("ck_desktop_channels_channel")
        ),
        sa.PrimaryKeyConstraint("channel", name=op.f("pk_desktop_channels")),
    )
    op.execute(grant_sql("desktop_channels", ["SELECT", "UPDATE"]))
    op.execute("INSERT INTO desktop_channels (channel) VALUES ('stable'), ('beta')")

    for table in ("candidate_refresh_tokens", "candidate_otps"):
        op.execute(grant_sql(table, ["SELECT"], role=AUTH_ROLE))
        op.execute(
            f"CREATE POLICY {table}_auth_lookup ON {table} FOR SELECT TO {AUTH_ROLE} USING (true)"
        )
    op.execute(REFRESH_LOOKUP_SQL)
    op.execute(CHALLENGE_LOOKUP_SQL)
    for function in FUNCTIONS:
        op.execute(f"ALTER FUNCTION {function} OWNER TO {AUTH_ROLE}")
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO {APP_ROLE}")


def downgrade() -> None:
    for function in FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
    op.drop_table("desktop_channels")
    op.drop_table("desktop_releases")
    op.drop_table("candidate_refresh_tokens")
    op.drop_table("candidate_otps")
    op.drop_table("candidate_devices")
    op.drop_column("organization_settings", "candidate_access")
