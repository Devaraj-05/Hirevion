"""Interviews and invitations (SP-07a): interviews pinned to a template version (PRD §24, §80),
their event history and reviewers, the invitations sent (PRD §25), and candidate accounts with
their single-use links. Also the job's interview template (PRD §11), the organisation's support
email, and the application stages `interview` and `interviewed`.

Candidate sign-in has to find an account by email before the organisation is known, so, like
recruiter sign-in (0006), two SECURITY DEFINER lookups belong to `hirevion_auth`. The scheduler
has to find due interviews across organisations: one listing function belongs to a new role,
`hirevion_scheduler`, which can't log in, doesn't bypass row-level security and reads only what
that function needs.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-09
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from hirevion_core.db.rls import grant_sql, tenant_policy_sql
from hirevion_core.settings import APP_ROLE, AUTH_ROLE, SCHEDULER_ROLE

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STAGES_BEFORE = (
    "uploaded",
    "parsed",
    "screened",
    "ranked",
    "review",
    "shortlisted",
    "rejected",
    "on_hold",
)
STAGES = (*STAGES_BEFORE, "interview", "interviewed")
STATUSES = (
    "scheduled",
    "invited",
    "in_progress",
    "interrupted",
    "completed",
    "evaluating",
    "evaluated",
    "expired",
    "cancelled",
    "abandoned",
)
ACTIVE = ("scheduled", "invited", "in_progress", "interrupted")
ACTORS = ("user", "candidate", "system", "agent")
KINDS = ("invitation", "reminder", "reschedule", "cancellation")

CANDIDATE_LOOKUP_SQL = """
CREATE FUNCTION auth_candidate_by_email(p_email citext)
RETURNS TABLE (
    account_id uuid, organization_id uuid, status text, password_hash text,
    organization_status text
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
AS $$
    SELECT a.id, a.organization_id, a.status, a.password_hash, o.status
    FROM candidate_accounts a
    JOIN organizations o ON o.id = a.organization_id
    WHERE a.email = p_email
    ORDER BY a.created_at
    LIMIT 10
$$
"""

CANDIDATE_LINK_SQL = """
CREATE FUNCTION auth_candidate_token(p_token_hash bytea, p_purpose text)
RETURNS TABLE (
    token_id uuid, organization_id uuid, account_id uuid, expires_at timestamptz,
    used_at timestamptz
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
AS $$
    SELECT t.id, t.organization_id, t.account_id, t.expires_at, t.used_at
    FROM candidate_tokens t
    WHERE t.token_hash = p_token_hash AND t.purpose = p_purpose
$$
"""

# Interviews due for a reminder or for expiry, in active organisations. The caller handles each
# in its tenant's transaction, under a row lock, and re-checks it there.
DUE_SQL = """
CREATE FUNCTION scheduler_due_interviews(p_now timestamptz, p_lead interval, p_limit integer)
RETURNS TABLE (organization_id uuid, interview_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
AS $$
    SELECT i.organization_id, i.id
    FROM interviews i
    JOIN organizations o ON o.id = i.organization_id AND o.status = 'active'
    WHERE (i.status IN ('scheduled', 'invited') AND i.expires_at <= p_now)
       OR (i.status = 'invited' AND i.start_reminder_sent_at IS NULL
           AND i.starts_at > p_now AND i.starts_at <= p_now + p_lead
           AND i.invited_at <= i.starts_at - p_lead)
       OR (i.status = 'invited' AND i.expiry_reminder_sent_at IS NULL
           AND i.starts_at <= p_now AND i.expires_at > p_now
           AND i.expires_at <= p_now + p_lead AND i.expires_at - i.starts_at > p_lead)
    ORDER BY i.expires_at
    LIMIT p_limit
$$
"""

AUTH_FUNCTIONS = ("auth_candidate_by_email(citext)", "auth_candidate_token(bytea, text)")
SCHEDULER_FUNCTIONS = ("scheduler_due_interviews(timestamptz, interval, integer)",)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _timestamps() -> list[sa.Column[datetime]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _created() -> sa.Column[datetime]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def _organization_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id"],
        ["organizations.id"],
        name=op.f(f"fk_{table}_organization_id_organizations"),
    )


def _composite_fk(
    table: str, column: str, target: str, ondelete: str | None = "CASCADE"
) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id", column],
        [f"{target}.organization_id", f"{target}.id"],
        name=op.f(f"fk_{table}_organization_id_{column}_{target}"),
        ondelete=ondelete,
    )


def _tenant(table: str, privileges: list[str]) -> None:
    op.create_index(op.f(f"ix_{table}_organization_id"), table, ["organization_id"])
    for statement in tenant_policy_sql(table):
        op.execute(statement)
    op.execute(grant_sql(table, privileges))


def _jsonb(name: str, default: str) -> sa.Column[object]:
    return sa.Column(
        name,
        postgresql.JSONB(),
        # (`default` is a constant of this migration: "{}" or "[]")
        # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
        server_default=sa.text(f"'{default}'::jsonb"),
        nullable=False,
    )


def _ts(name: str) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=True)


def upgrade() -> None:
    op.add_column("organizations", sa.Column("support_email", postgresql.CITEXT(), nullable=True))
    op.add_column("jobs", sa.Column("interview_template_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_jobs_organization_id_interview_template_id_interview_templates"),
        "jobs",
        "interview_templates",
        ["organization_id", "interview_template_id"],
        ["organization_id", "id"],
    )
    op.drop_constraint(op.f("ck_applications_stage"), "applications", type_="check")
    op.create_check_constraint(op.f("ck_applications_stage"), "applications", _in("stage", STAGES))

    op.create_table(
        "candidate_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("locale", sa.Text(), server_default="en-IN", nullable=False),
        sa.Column("status", sa.Text(), server_default="invited", nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        _ts("password_changed_at"),
        _ts("email_verified_at"),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('invited', 'active', 'disabled')", name=op.f("ck_candidate_accounts_status")
        ),
        _organization_fk("candidate_accounts"),
        _composite_fk("candidate_accounts", "candidate_id", "candidates"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_accounts")),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_candidate_accounts_organization_id_id")
        ),
        sa.UniqueConstraint(
            "organization_id",
            "candidate_id",
            name=op.f("uq_candidate_accounts_organization_id_candidate_id"),
        ),
        sa.UniqueConstraint(
            "organization_id", "email", name=op.f("uq_candidate_accounts_organization_id_email")
        ),
    )
    op.create_index("ix_candidate_accounts_email", "candidate_accounts", ["email"])
    _tenant("candidate_accounts", ["SELECT", "INSERT", "UPDATE"])

    op.create_table(
        "candidate_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        _created(),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _ts("used_at"),
        sa.CheckConstraint(
            "purpose IN ('set_password', 'reset_password')",
            name=op.f("ck_candidate_tokens_purpose"),
        ),
        _organization_fk("candidate_tokens"),
        _composite_fk("candidate_tokens", "account_id", "candidate_accounts"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_candidate_tokens_token_hash")),
    )
    op.create_index("ix_candidate_tokens_account_id", "candidate_tokens", ["account_id"])
    _tenant("candidate_tokens", ["SELECT", "INSERT", "UPDATE"])

    op.create_table(
        "interviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_account_id", sa.Uuid(), nullable=True),
        sa.Column("template_id", sa.Uuid(), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), server_default="scheduled", nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.Text(), server_default="Asia/Kolkata", nullable=False),
        sa.Column("locale", sa.Text(), server_default="en-IN", nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        _jsonb("policy", "{}"),
        _jsonb("questions", "[]"),
        sa.Column("team_id", sa.Uuid(), nullable=True),
        sa.Column("recruiter_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        _ts("invited_at"),
        _ts("started_at"),
        _ts("completed_at"),
        _ts("ended_at"),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        _ts("start_reminder_sent_at"),
        _ts("expiry_reminder_sent_at"),
        sa.Column("reschedule_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(_in("status", STATUSES), name=op.f("ck_interviews_status")),
        sa.CheckConstraint("starts_at < expires_at", name=op.f("ck_interviews_window")),
        sa.CheckConstraint(
            "duration_minutes BETWEEN 15 AND 360", name=op.f("ck_interviews_duration")
        ),
        sa.CheckConstraint("reschedule_count >= 0", name=op.f("ck_interviews_reschedule_count")),
        _organization_fk("interviews"),
        _composite_fk("interviews", "application_id", "applications"),
        _composite_fk("interviews", "candidate_id", "candidates"),
        _composite_fk("interviews", "job_id", "jobs"),
        _composite_fk("interviews", "template_id", "interview_templates", ondelete=None),
        sa.ForeignKeyConstraint(
            ["template_id", "template_version"],
            ["interview_template_versions.template_id", "interview_template_versions.version"],
            name=op.f("fk_interviews_template_id_template_version_interview_template_versions"),
        ),
        _composite_fk("interviews", "candidate_account_id", "candidate_accounts", ondelete=None),
        _composite_fk("interviews", "team_id", "teams", ondelete=None),
        sa.ForeignKeyConstraint(
            ["organization_id", "recruiter_id"],
            ["users.organization_id", "users.id"],
            name=op.f("fk_interviews_organization_id_recruiter_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_interviews")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_interviews_organization_id_id")),
        sa.UniqueConstraint(
            "organization_id", "number", name=op.f("uq_interviews_organization_id_number")
        ),
    )
    op.create_index("ix_interviews_application_id", "interviews", ["application_id"])
    op.create_index("ix_interviews_candidate_id", "interviews", ["candidate_id"])
    op.create_index("ix_interviews_status_expires_at", "interviews", ["status", "expires_at"])
    op.create_index(
        "uq_interviews_active_application",
        "interviews",
        ["application_id"],
        unique=True,
        postgresql_where=sa.text(_in("status", ACTIVE)),
    )
    _tenant("interviews", ["SELECT", "INSERT", "UPDATE"])

    op.create_table(
        "interview_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.Text(), nullable=True),
        sa.Column("to_status", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=True),
        _jsonb("details", "{}"),
        _created(),
        sa.CheckConstraint(_in("actor_type", ACTORS), name=op.f("ck_interview_events_actor_type")),
        _organization_fk("interview_events"),
        _composite_fk("interview_events", "interview_id", "interviews"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_interview_events")),
    )
    op.create_index(op.f("ix_interview_events_interview_id"), "interview_events", ["interview_id"])
    _tenant("interview_events", ["SELECT", "INSERT"])

    op.create_table(
        "interview_reviewers",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        _created(),
        _organization_fk("interview_reviewers"),
        _composite_fk("interview_reviewers", "interview_id", "interviews"),
        sa.ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["users.organization_id", "users.id"],
            name=op.f("fk_interview_reviewers_organization_id_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("interview_id", "user_id", name=op.f("pk_interview_reviewers")),
    )
    op.create_index("ix_interview_reviewers_user_id", "interview_reviewers", ["user_id"])
    _tenant("interview_reviewers", ["SELECT", "INSERT", "DELETE"])

    op.create_table(
        "invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("sent_to", postgresql.CITEXT(), nullable=False),
        sa.Column("locale", sa.Text(), nullable=False),
        _jsonb("contents", "{}"),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        _created(),
        sa.CheckConstraint(_in("kind", KINDS), name=op.f("ck_invitations_kind")),
        _organization_fk("invitations"),
        _composite_fk("invitations", "interview_id", "interviews"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invitations")),
    )
    op.create_index(op.f("ix_invitations_interview_id"), "invitations", ["interview_id"])
    _tenant("invitations", ["SELECT", "INSERT"])

    # Candidate sign-in lookups, owned by the lookup role (ADR-0013's pattern).
    for table in ("candidate_accounts", "candidate_tokens"):
        op.execute(grant_sql(table, ["SELECT"], role=AUTH_ROLE))
        op.execute(
            f"CREATE POLICY {table}_auth_lookup ON {table} FOR SELECT TO {AUTH_ROLE} USING (true)"
        )
    op.execute(CANDIDATE_LOOKUP_SQL)
    op.execute(CANDIDATE_LINK_SQL)
    for function in AUTH_FUNCTIONS:
        op.execute(f"ALTER FUNCTION {function} OWNER TO {AUTH_ROLE}")
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO {APP_ROLE}")

    # The scheduler's listing role. Roles are cluster-wide: the test database may have it.
    role_exists = (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": SCHEDULER_ROLE})
        .scalar()
    )
    if not role_exists:
        op.execute(
            f"CREATE ROLE {SCHEDULER_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB "
            "NOCREATEROLE NOREPLICATION"
        )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {SCHEDULER_ROLE}")
    for table in ("interviews", "organizations"):
        op.execute(grant_sql(table, ["SELECT"], role=SCHEDULER_ROLE))
        op.execute(
            f"CREATE POLICY {table}_scheduler ON {table} FOR SELECT TO {SCHEDULER_ROLE} "
            "USING (true)"
        )
    op.execute(DUE_SQL)
    for function in SCHEDULER_FUNCTIONS:
        op.execute(f"ALTER FUNCTION {function} OWNER TO {SCHEDULER_ROLE}")
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO {APP_ROLE}")


def downgrade() -> None:
    for function in (*SCHEDULER_FUNCTIONS, *AUTH_FUNCTIONS):
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
    op.execute("DROP POLICY IF EXISTS organizations_scheduler ON organizations")
    # (the role and table names are constants of the migration)
    op.execute(f"REVOKE SELECT ON organizations FROM {SCHEDULER_ROLE}")  # noqa: S608  # nosec B608
    op.drop_table("invitations")
    op.drop_table("interview_reviewers")
    op.drop_table("interview_events")
    op.drop_table("interviews")
    op.drop_table("candidate_tokens")
    op.drop_table("candidate_accounts")
    op.drop_constraint(op.f("ck_applications_stage"), "applications", type_="check")
    op.create_check_constraint(
        op.f("ck_applications_stage"), "applications", _in("stage", STAGES_BEFORE)
    )
    op.drop_constraint(
        op.f("fk_jobs_organization_id_interview_template_id_interview_templates"),
        "jobs",
        type_="foreignkey",
    )
    op.drop_column("jobs", "interview_template_id")
    op.drop_column("organizations", "support_email")
    # The scheduler role is cluster-wide and may serve another database, so it stays.
