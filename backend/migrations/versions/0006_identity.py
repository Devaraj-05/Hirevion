"""Identity: users, web sessions, emailed tokens, roles, and the sign-in lookup functions.

Sign-in must find a user (and every API call its session) before the organisation is known.
Two SECURITY DEFINER functions do that. They belong to `hirevion_auth`, a role that can't log in
and doesn't bypass row-level security: it has a read-only, all-rows policy on just the tables
they read, and the application role may only execute them (SP-02 spec, ADR-0013).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-01
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from hirevion_core.db.rls import grant_sql, tenant_policy_sql
from hirevion_core.settings import APP_ROLE, AUTH_ROLE

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PLATFORM_ORGANIZATION_ID = UUID("00000000-0000-7000-8000-000000000001")
PLATFORM_SUPER_ADMIN_ROLE_ID = UUID("00000000-0000-7000-8000-000000000002")

LOOKUP_TABLES = ("users", "organizations", "web_sessions")

USER_LOOKUP_SQL = """
CREATE FUNCTION auth_user_by_email(p_email citext)
RETURNS TABLE (
    user_id uuid, organization_id uuid, status text, password_hash text,
    organization_status text
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
AS $$
    SELECT u.id, u.organization_id, u.status, u.password_hash, o.status
    FROM users u
    JOIN organizations o ON o.id = u.organization_id
    WHERE u.email = p_email
$$
"""

SESSION_LOOKUP_SQL = """
CREATE FUNCTION auth_session(p_token_hash bytea)
RETURNS TABLE (
    session_id uuid, user_id uuid, organization_id uuid, csrf_hash bytea,
    last_seen_at timestamptz, expires_at timestamptz, revoked_at timestamptz,
    user_status text, organization_status text
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
AS $$
    SELECT s.id, s.user_id, s.organization_id, s.csrf_hash, s.last_seen_at, s.expires_at,
           s.revoked_at, u.status, o.status
    FROM web_sessions s
    JOIN users u ON u.organization_id = s.organization_id AND u.id = s.user_id
    JOIN organizations o ON o.id = s.organization_id
    WHERE s.token_hash = p_token_hash
$$
"""

FUNCTIONS = ("auth_user_by_email(citext)", "auth_session(bytea)")


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


def _user_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id", "user_id"],
        ["users.organization_id", "users.id"],
        name=op.f(f"fk_{table}_organization_id_user_id_users"),
        ondelete="CASCADE",
    )


def _tenant(table: str, privileges: list[str]) -> None:
    op.create_index(op.f(f"ix_{table}_organization_id"), table, ["organization_id"])
    for statement in tenant_policy_sql(table):
        op.execute(statement)
    op.execute(grant_sql(table, privileges))


def upgrade() -> None:
    # Roles are cluster-wide: another database (the test one) may have created it already.
    role_exists = (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": AUTH_ROLE})
        .scalar()
    )
    if not role_exists:
        op.execute(
            f"CREATE ROLE {AUTH_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE "
            "NOREPLICATION"
        )

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("locale", sa.Text(), server_default="en-IN", nullable=False),
        sa.Column("status", sa.Text(), server_default="invited", nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('invited', 'active', 'disabled')", name=op.f("ck_users_status")
        ),
        _organization_fk("users"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_users_organization_id_id")),
    )
    _tenant("users", ["SELECT", "INSERT", "UPDATE"])

    op.create_table(
        "web_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("csrf_hash", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        _organization_fk("web_sessions"),
        _user_fk("web_sessions"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_web_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_web_sessions_token_hash")),
    )
    op.create_index("ix_web_sessions_user_id", "web_sessions", ["user_id"])
    _tenant("web_sessions", ["SELECT", "INSERT", "UPDATE"])

    op.create_table(
        "auth_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("new_email", postgresql.CITEXT(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "purpose IN ('set_password', 'reset_password', 'verify_email')",
            name=op.f("ck_auth_tokens_purpose"),
        ),
        _organization_fk("auth_tokens"),
        _user_fk("auth_tokens"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_auth_tokens_token_hash")),
    )
    op.create_index("ix_auth_tokens_user_id", "auth_tokens", ["user_id"])
    _tenant("auth_tokens", ["SELECT", "INSERT", "UPDATE"])

    op.create_table(
        "roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("system", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        *_timestamps(),
        _organization_fk("roles"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles")),
        sa.UniqueConstraint("organization_id", "key", name=op.f("uq_roles_organization_id_key")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_roles_organization_id_id")),
    )
    _tenant("roles", ["SELECT", "INSERT", "UPDATE"])

    op.create_table(
        "user_roles",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        _organization_fk("user_roles"),
        _user_fk("user_roles"),
        sa.ForeignKeyConstraint(
            ["organization_id", "role_id"],
            ["roles.organization_id", "roles.id"],
            name=op.f("fk_user_roles_organization_id_role_id_roles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "role_id", name=op.f("pk_user_roles")),
    )
    op.create_index("ix_user_roles_role_id", "user_roles", ["role_id"])
    _tenant("user_roles", ["SELECT", "INSERT", "DELETE"])

    # The lookup role reads exactly what the two functions need, in every organisation. It needs
    # the schema too: a recreated `public` grants nothing to PUBLIC.
    op.execute(f"GRANT USAGE ON SCHEMA public TO {AUTH_ROLE}")
    for table in LOOKUP_TABLES:
        op.execute(grant_sql(table, ["SELECT"], role=AUTH_ROLE))
        op.execute(
            f"CREATE POLICY {table}_auth_lookup ON {table} FOR SELECT TO {AUTH_ROLE} USING (true)"
        )
    op.execute(USER_LOOKUP_SQL)
    op.execute(SESSION_LOOKUP_SQL)
    for function in FUNCTIONS:
        op.execute(f"ALTER FUNCTION {function} OWNER TO {AUTH_ROLE}")
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO {APP_ROLE}")

    op.execute(
        sa.text(
            "INSERT INTO organizations (id, name, slug) VALUES (:id, 'Platform', 'platform')"
        ).bindparams(id=PLATFORM_ORGANIZATION_ID)
    )
    op.execute(
        sa.text(
            "INSERT INTO roles (id, organization_id, key, name, system) "
            "VALUES (:id, :organization_id, 'super_admin', 'Super admin', true)"
        ).bindparams(id=PLATFORM_SUPER_ADMIN_ROLE_ID, organization_id=PLATFORM_ORGANIZATION_ID)
    )


def downgrade() -> None:
    for function in reversed(FUNCTIONS):
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
    op.drop_table("user_roles")
    op.drop_table("roles")
    op.drop_table("auth_tokens")
    op.drop_table("web_sessions")
    op.drop_table("users")
    # `organizations` is the only lookup table that outlives this migration.
    op.execute("DROP POLICY IF EXISTS organizations_auth_lookup ON organizations")
    # (the role and table names are constants of the migration)
    op.execute(f"REVOKE SELECT ON organizations FROM {AUTH_ROLE}")  # noqa: S608  # nosec B608
    op.execute(
        sa.text("DELETE FROM organizations WHERE id = :id").bindparams(id=PLATFORM_ORGANIZATION_ID)
    )
    # The role is cluster-wide and may serve other databases (the test database), so it stays.
