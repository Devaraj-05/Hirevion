"""The candidate portal (SP-07b): candidates' web sessions and the requests they make.

A portal session arrives as a cookie before its organisation is known, so its lookup is a
SECURITY DEFINER function owned by `hirevion_auth`, as the recruiter's is (0006).

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-12
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from hirevion_core.db.rls import grant_sql, tenant_policy_sql
from hirevion_core.settings import APP_ROLE, AUTH_ROLE

revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KINDS = (
    "reschedule",
    "support",
    "accommodation",
    "alternative_process",
    "data_access",
    "data_correction",
    "data_erasure",
    "grievance",
    "nomination",
    "consent_withdrawal",
)
STATUSES = ("open", "in_progress", "resolved", "declined")

SESSION_LOOKUP_SQL = """
CREATE FUNCTION auth_candidate_session(p_token_hash bytea)
RETURNS TABLE (
    session_id uuid, account_id uuid, organization_id uuid, csrf_hash bytea,
    last_seen_at timestamptz, expires_at timestamptz, revoked_at timestamptz,
    account_status text, organization_status text
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
AS $$
    SELECT s.id, s.account_id, s.organization_id, s.csrf_hash, s.last_seen_at, s.expires_at,
           s.revoked_at, a.status, o.status
    FROM candidate_web_sessions s
    JOIN candidate_accounts a ON a.organization_id = s.organization_id AND a.id = s.account_id
    JOIN organizations o ON o.id = s.organization_id
    WHERE s.token_hash = p_token_hash
$$
"""

FUNCTION = "auth_candidate_session(bytea)"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _ts(name: str, nullable: bool = True) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _created(name: str = "created_at") -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _organization_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id"],
        ["organizations.id"],
        name=op.f(f"fk_{table}_organization_id_organizations"),
    )


def _composite_fk(
    table: str, column: str, target: str, cascade: bool = True
) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id", column],
        [f"{target}.organization_id", f"{target}.id"],
        name=op.f(f"fk_{table}_organization_id_{column}_{target}"),
        ondelete="CASCADE" if cascade else None,
    )


def _tenant(table: str, privileges: list[str]) -> None:
    op.create_index(op.f(f"ix_{table}_organization_id"), table, ["organization_id"])
    for statement in tenant_policy_sql(table):
        op.execute(statement)
    op.execute(grant_sql(table, privileges))


def upgrade() -> None:
    op.create_table(
        "candidate_web_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("csrf_hash", sa.LargeBinary(), nullable=False),
        _created(),
        _ts("last_seen_at", nullable=False),
        _ts("expires_at", nullable=False),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        _ts("revoked_at"),
        _organization_fk("candidate_web_sessions"),
        _composite_fk("candidate_web_sessions", "account_id", "candidate_accounts"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_web_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_candidate_web_sessions_token_hash")),
    )
    op.create_index(
        "ix_candidate_web_sessions_account_id", "candidate_web_sessions", ["account_id"]
    )
    _tenant("candidate_web_sessions", ["SELECT", "INSERT", "UPDATE"])

    op.create_table(
        "candidate_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("interview_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="open", nullable=False),
        sa.Column("message", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column("handled_by", sa.Uuid(), nullable=True),
        _ts("handled_at"),
        _created(),
        _created("updated_at"),
        sa.CheckConstraint(_in("kind", KINDS), name=op.f("ck_candidate_requests_kind")),
        sa.CheckConstraint(_in("status", STATUSES), name=op.f("ck_candidate_requests_status")),
        _organization_fk("candidate_requests"),
        _composite_fk("candidate_requests", "account_id", "candidate_accounts"),
        _composite_fk("candidate_requests", "candidate_id", "candidates"),
        _composite_fk("candidate_requests", "interview_id", "interviews"),
        _composite_fk("candidate_requests", "handled_by", "users", cascade=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_requests")),
    )
    op.create_index("ix_candidate_requests_account_id", "candidate_requests", ["account_id"])
    op.create_index("ix_candidate_requests_interview_id", "candidate_requests", ["interview_id"])
    op.create_index(
        "ix_candidate_requests_status_created_at", "candidate_requests", ["status", "created_at"]
    )
    _tenant("candidate_requests", ["SELECT", "INSERT", "UPDATE"])

    op.execute(grant_sql("candidate_web_sessions", ["SELECT"], role=AUTH_ROLE))
    op.execute(
        "CREATE POLICY candidate_web_sessions_auth_lookup ON candidate_web_sessions "
        f"FOR SELECT TO {AUTH_ROLE} USING (true)"
    )
    op.execute(SESSION_LOOKUP_SQL)
    op.execute(f"ALTER FUNCTION {FUNCTION} OWNER TO {AUTH_ROLE}")
    op.execute(f"REVOKE ALL ON FUNCTION {FUNCTION} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {FUNCTION} TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}")
    op.drop_table("candidate_requests")
    op.drop_table("candidate_web_sessions")
