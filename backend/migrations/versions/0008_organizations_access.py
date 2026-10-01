"""Organisations and access: profile columns, departments, teams, custom-role permissions, the
users' access scope, step-up, and the platform's organisation listing (SP-02b, ADR-0014).

- The application role may now insert an organisation, but only inside that organisation's own
  tenant transaction: the existing `organizations_tenant` policy checks `id` on insert too.
- `platform_organizations()` lists every organisation for the super admins' pages. Like the
  sign-in lookups it belongs to `hirevion_auth`, which already reads `organizations` and `users`
  through all-rows policies; the application role may only execute it.
- `auth_session()` now also returns `stepped_up_at`, so a changed return type means drop and
  create.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-02
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from hirevion_core.db.rls import grant_sql, tenant_policy_sql
from hirevion_core.settings import APP_ROLE, AUTH_ROLE

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SESSION_LOOKUP = "auth_session(bytea)"
ORGANIZATION_LISTING = "platform_organizations()"

SESSION_LOOKUP_SQL = """
CREATE FUNCTION auth_session(p_token_hash bytea)
RETURNS TABLE (
    session_id uuid, user_id uuid, organization_id uuid, csrf_hash bytea,
    last_seen_at timestamptz, expires_at timestamptz, revoked_at timestamptz,
    stepped_up_at timestamptz, user_status text, organization_status text
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
AS $$
    SELECT s.id, s.user_id, s.organization_id, s.csrf_hash, s.last_seen_at, s.expires_at,
           s.revoked_at, s.stepped_up_at, u.status, o.status
    FROM web_sessions s
    JOIN users u ON u.organization_id = s.organization_id AND u.id = s.user_id
    JOIN organizations o ON o.id = s.organization_id
    WHERE s.token_hash = p_token_hash
$$
"""

# 0006's version, restored on downgrade.
PREVIOUS_SESSION_LOOKUP_SQL = """
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

ORGANIZATION_LISTING_SQL = """
CREATE FUNCTION platform_organizations()
RETURNS TABLE (
    id uuid, name text, slug citext, status text, created_at timestamptz, user_count bigint
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
AS $$
    SELECT o.id, o.name, o.slug, o.status, o.created_at,
           (SELECT count(*) FROM users u WHERE u.organization_id = o.id)
    FROM organizations o
$$
"""


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


def _tenant(table: str, privileges: list[str]) -> None:
    op.create_index(op.f(f"ix_{table}_organization_id"), table, ["organization_id"])
    for statement in tenant_policy_sql(table):
        op.execute(statement)
    op.execute(grant_sql(table, privileges))


def _own_function(function: str) -> None:
    op.execute(f"ALTER FUNCTION {function} OWNER TO {AUTH_ROLE}")
    op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO {APP_ROLE}")


def upgrade() -> None:
    # The organisation profile (PRD §9).
    op.add_column("organizations", sa.Column("website", sa.Text(), nullable=True))
    op.add_column(
        "organizations", sa.Column("country", sa.Text(), server_default="IN", nullable=False)
    )
    op.add_column(
        "organizations",
        sa.Column("timezone", sa.Text(), server_default="Asia/Kolkata", nullable=False),
    )
    op.add_column(
        "organizations",
        sa.Column("default_locale", sa.Text(), server_default="en-IN", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_organizations_country"), "organizations", "country ~ '^[A-Z]{2}$'"
    )
    op.create_check_constraint(
        op.f("ck_organizations_default_locale"),
        "organizations",
        "default_locale IN ('en-IN', 'en-US')",
    )
    # Creating an organisation happens inside its own tenant (the policy checks `id`).
    op.execute(grant_sql("organizations", ["INSERT"]))

    op.create_table(
        "departments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", postgresql.CITEXT(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        _organization_fk("departments"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_departments")),
        sa.UniqueConstraint(
            "organization_id", "name", name=op.f("uq_departments_organization_id_name")
        ),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_departments_organization_id_id")
        ),
    )
    _tenant("departments", ["SELECT", "INSERT", "UPDATE"])

    op.create_table(
        "teams",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", postgresql.CITEXT(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("department_id", sa.Uuid(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        _organization_fk("teams"),
        sa.ForeignKeyConstraint(
            ["organization_id", "department_id"],
            ["departments.organization_id", "departments.id"],
            name=op.f("fk_teams_organization_id_department_id_departments"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_teams")),
        sa.UniqueConstraint("organization_id", "name", name=op.f("uq_teams_organization_id_name")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_teams_organization_id_id")),
    )
    _tenant("teams", ["SELECT", "INSERT", "UPDATE"])

    op.create_table(
        "team_members",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        _organization_fk("team_members"),
        sa.ForeignKeyConstraint(
            ["organization_id", "team_id"],
            ["teams.organization_id", "teams.id"],
            name=op.f("fk_team_members_organization_id_team_id_teams"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["users.organization_id", "users.id"],
            name=op.f("fk_team_members_organization_id_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("team_id", "user_id", name=op.f("pk_team_members")),
    )
    op.create_index("ix_team_members_user_id", "team_members", ["user_id"])
    _tenant("team_members", ["SELECT", "INSERT", "DELETE"])

    # Custom roles: a description, case-insensitive unique names (system names included), and
    # their permissions. System roles keep theirs in code.
    op.add_column("roles", sa.Column("description", sa.Text(), nullable=True))
    op.alter_column(
        "roles", "name", type_=postgresql.CITEXT(), existing_type=sa.Text(), nullable=False
    )
    op.create_unique_constraint(
        op.f("uq_roles_organization_id_name"), "roles", ["organization_id", "name"]
    )
    op.execute(grant_sql("roles", ["DELETE"]))
    op.create_table(
        "role_permissions",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("permission", sa.Text(), nullable=False),
        sa.CheckConstraint(
            r"permission ~ '^[a-z_]+(\.[a-z_]+)+$'", name=op.f("ck_role_permissions_permission")
        ),
        _organization_fk("role_permissions"),
        sa.ForeignKeyConstraint(
            ["organization_id", "role_id"],
            ["roles.organization_id", "roles.id"],
            name=op.f("fk_role_permissions_organization_id_role_id_roles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("role_id", "permission", name=op.f("pk_role_permissions")),
    )
    _tenant("role_permissions", ["SELECT", "INSERT", "DELETE"])

    # Users: the resource scope, and deleting a cancelled invitation.
    op.add_column(
        "users",
        sa.Column("access_scope", sa.Text(), server_default="organization", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_users_access_scope"), "users", "access_scope IN ('organization', 'teams')"
    )
    op.execute(grant_sql("users", ["DELETE"]))

    # Step-up.
    op.add_column(
        "web_sessions", sa.Column("stepped_up_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(f"DROP FUNCTION {SESSION_LOOKUP}")
    op.execute(SESSION_LOOKUP_SQL)
    _own_function(SESSION_LOOKUP)

    op.execute(ORGANIZATION_LISTING_SQL)
    _own_function(ORGANIZATION_LISTING)


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {ORGANIZATION_LISTING}")
    op.execute(f"DROP FUNCTION IF EXISTS {SESSION_LOOKUP}")
    op.execute(PREVIOUS_SESSION_LOOKUP_SQL)
    _own_function(SESSION_LOOKUP)
    op.drop_column("web_sessions", "stepped_up_at")

    op.execute(f"REVOKE DELETE ON users FROM {APP_ROLE}")
    op.drop_constraint(op.f("ck_users_access_scope"), "users", type_="check")
    op.drop_column("users", "access_scope")

    op.drop_table("role_permissions")
    op.execute(f"REVOKE DELETE ON roles FROM {APP_ROLE}")
    op.drop_constraint(op.f("uq_roles_organization_id_name"), "roles", type_="unique")
    op.alter_column(
        "roles", "name", type_=sa.Text(), existing_type=postgresql.CITEXT(), nullable=False
    )
    op.drop_column("roles", "description")

    op.drop_table("team_members")
    op.drop_table("teams")
    op.drop_table("departments")

    op.execute(f"REVOKE INSERT ON organizations FROM {APP_ROLE}")
    op.drop_constraint(op.f("ck_organizations_default_locale"), "organizations", type_="check")
    op.drop_constraint(op.f("ck_organizations_country"), "organizations", type_="check")
    for column in ("default_locale", "timezone", "country", "website"):
        op.drop_column("organizations", column)
