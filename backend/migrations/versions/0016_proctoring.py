"""Proctoring (SP-14): the platform's catalogue of application categories and rules (seeded), the
proctor session of an interview with the policy it is pinned to, the events judged under it, their
evidence and the recruiter's reviews. `proctor_events` is not partitioned: its idempotency key
(session, seq) and the in-place update of an episode need unique indexes that a partition key
would break. `scheduler_proctor_sessions_due` lists the sessions the watcher must look at, the way
`scheduler_due_interviews` lists interviews.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-10
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from hirevion_core.db.rls import CURRENT_ORG, grant_sql, tenant_policy_sql
from hirevion_core.ids import uuid7
from hirevion_core.settings import APP_ROLE, SCHEDULER_ROLE

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEVERITIES = ("INFO", "WARNING", "CRITICAL")
PHASES = ("started", "escalated", "ended")
REVIEW_STATUSES = ("pending", "confirmed", "false_positive", "not_relevant")
EVIDENCE_KINDS = (
    "screenshot",
    "video_segment",
    "camera_segment",
    "third_eye_segment",
    "screen_segment",
    "transcript_segment",
    "process_metadata",
)

DUE_SQL = """
CREATE FUNCTION scheduler_proctor_sessions_due(p_now timestamptz, p_limit integer)
RETURNS TABLE (organization_id uuid, proctor_session_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
AS $$
    SELECT s.organization_id, s.id
    FROM proctor_sessions s
    JOIN organizations o ON o.id = s.organization_id AND o.status = 'active'
    WHERE s.status = 'open' AND s.watch_at IS NOT NULL AND s.watch_at <= p_now
    ORDER BY s.watch_at
    LIMIT p_limit
$$
"""
DUE_FUNCTION = "scheduler_proctor_sessions_due(timestamptz, integer)"

# The platform's catalogue (PRD §61). Publishers are the signer's subject name, which the
# desktop compares exactly (ignoring case); where a vendor signs many products, the rule also
# names the executable. A blocking rule never matches on the name alone.
CATEGORIES = [
    ("remote_access", "Remote access and control", "CRITICAL"),
    ("screen_sharing", "Meetings and screen sharing", "CRITICAL"),
    ("ai_assistant", "AI assistants and overlays", "CRITICAL"),
    ("messaging", "Messaging", "WARNING"),
    ("screen_recorder", "Screen recorders", "CRITICAL"),
    ("virtual_machine", "Virtual machines and emulators", "CRITICAL"),
]
# (category, match, value, extra conditions)
RULES: list[tuple[str, str, str, list[dict[str, str]]]] = [
    ("remote_access", "publisher", "TeamViewer Germany GmbH", []),
    ("remote_access", "publisher", "TeamViewer GmbH", []),
    ("remote_access", "publisher", "AnyDesk Software GmbH", []),
    ("remote_access", "publisher", "philandro Software GmbH", []),
    ("remote_access", "publisher", "Splashtop Inc.", []),
    ("remote_access", "publisher", "RealVNC Limited", []),
    ("remote_access", "publisher", "LogMeIn, Inc.", []),
    ("remote_access", "publisher", "GoTo Group, Inc.", []),
    ("remote_access", "publisher", "Parsec Cloud, Inc.", []),
    ("remote_access", "name", "remoting_host", [{"match": "publisher", "value": "Google LLC"}]),
    ("remote_access", "name", "rustdesk", [{"match": "window_title", "value": "RustDesk"}]),
    ("remote_access", "name", "ultraviewer", [{"match": "window_title", "value": "UltraViewer"}]),
    ("screen_sharing", "publisher", "Zoom Video Communications, Inc.", []),
    ("screen_sharing", "publisher", "Discord Inc.", []),
    (
        "screen_sharing",
        "name",
        "ms-teams",
        [{"match": "publisher", "value": "Microsoft Corporation"}],
    ),
    ("screen_sharing", "name", "teams", [{"match": "publisher", "value": "Microsoft Corporation"}]),
    ("screen_sharing", "name", "skype", [{"match": "publisher", "value": "Microsoft Corporation"}]),
    (
        "screen_sharing",
        "name",
        "slack",
        [{"match": "publisher", "value": "Slack Technologies, LLC"}],
    ),
    ("screen_sharing", "name", "webex", [{"match": "publisher", "value": "Cisco Systems, Inc."}]),
    ("ai_assistant", "name", "cluely", [{"match": "window_title", "value": "Cluely"}]),
    ("ai_assistant", "window_title", "Final Round AI", []),
    ("ai_assistant", "window_title", "Interview Coder", []),
    ("ai_assistant", "window_title", "LockedIn AI", []),
    ("ai_assistant", "window_title", "Parakeet AI", []),
    ("ai_assistant", "name", "chatgpt", [{"match": "publisher", "value": "OpenAI OpCo, LLC"}]),
    ("ai_assistant", "name", "claude", [{"match": "publisher", "value": "Anthropic, PBC"}]),
    ("messaging", "publisher", "WhatsApp LLC", []),
    ("messaging", "publisher", "WhatsApp Inc.", []),
    ("messaging", "publisher", "Telegram FZ-LLC", []),
    ("messaging", "publisher", "Signal Messenger, LLC", []),
    ("screen_recorder", "publisher", "TechSmith Corporation", []),
    ("screen_recorder", "publisher", "Bandicam Company", []),
    ("screen_recorder", "name", "obs64", [{"match": "window_title", "value": "OBS"}]),
    ("screen_recorder", "name", "sharex", [{"match": "window_title", "value": "ShareX"}]),
    ("virtual_machine", "publisher", "VMware, Inc.", []),
    ("virtual_machine", "publisher", "BlueStack Systems, Inc.", []),
    (
        "virtual_machine",
        "name",
        "virtualboxvm",
        [{"match": "publisher", "value": "Oracle Corporation"}],
    ),
    (
        "virtual_machine",
        "name",
        "vmconnect",
        [{"match": "publisher", "value": "Microsoft Corporation"}],
    ),
]


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _created() -> sa.Column[datetime]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def _timestamps() -> list[sa.Column[datetime]]:
    return [
        _created(),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _ts(name: str, nullable: bool = True) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _jsonb(name: str, default: str) -> sa.Column[Any]:
    return sa.Column(
        name, postgresql.JSONB(), server_default=sa.text(f"'{default}'::jsonb"), nullable=False
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


def upgrade() -> None:
    op.create_table(
        "app_categories",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("severity", sa.Text(), server_default="CRITICAL", nullable=False),
        _created(),
        sa.CheckConstraint(
            "severity IN ('WARNING', 'CRITICAL')", name=op.f("ck_app_categories_severity")
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_app_categories")),
    )
    op.execute(grant_sql("app_categories", ["SELECT"]))

    op.create_table(
        "app_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("category_key", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), server_default="block", nullable=False),
        sa.Column("match", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        _jsonb("conditions", "[]"),
        sa.Column("label", sa.Text(), server_default="", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("action IN ('block', 'allow')", name=op.f("ck_app_rules_action")),
        sa.CheckConstraint(
            _in("match", ("name", "path", "publisher", "signature", "hash", "window_title")),
            name=op.f("ck_app_rules_match"),
        ),
        sa.CheckConstraint(
            "action = 'allow' OR match <> 'name' OR jsonb_array_length(conditions) > 0",
            name=op.f("ck_app_rules_name_alone"),
        ),
        _organization_fk("app_rules"),
        sa.ForeignKeyConstraint(
            ["category_key"],
            ["app_categories.key"],
            name=op.f("fk_app_rules_category_key_app_categories"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_rules")),
    )
    op.create_index("ix_app_rules_organization_id", "app_rules", ["organization_id"])
    # Everyone reads the platform's rules (no organisation); an organisation writes only its own.
    op.execute("ALTER TABLE app_rules ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE app_rules FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY app_rules_read ON app_rules FOR SELECT TO {APP_ROLE} "
        f"USING (organization_id IS NULL OR organization_id = {CURRENT_ORG})"
    )
    op.execute(
        f"CREATE POLICY app_rules_insert ON app_rules FOR INSERT TO {APP_ROLE} "
        f"WITH CHECK (organization_id = {CURRENT_ORG})"
    )
    op.execute(
        f"CREATE POLICY app_rules_update ON app_rules FOR UPDATE TO {APP_ROLE} "
        f"USING (organization_id = {CURRENT_ORG}) WITH CHECK (organization_id = {CURRENT_ORG})"
    )
    op.execute(
        f"CREATE POLICY app_rules_delete ON app_rules FOR DELETE TO {APP_ROLE} "
        f"USING (organization_id = {CURRENT_ORG})"
    )
    op.execute(grant_sql("app_rules", ["SELECT", "INSERT", "UPDATE", "DELETE"]))

    categories = sa.table(
        "app_categories", sa.column("key"), sa.column("name"), sa.column("severity")
    )
    op.bulk_insert(
        categories, [{"key": key, "name": name, "severity": s} for key, name, s in CATEGORIES]
    )
    rules = sa.table(
        "app_rules",
        sa.column("id", sa.Uuid()),
        sa.column("category_key"),
        sa.column("action"),
        sa.column("match"),
        sa.column("value"),
        sa.column("conditions", postgresql.JSONB()),
        sa.column("label"),
    )
    op.bulk_insert(
        rules,
        [
            {
                "id": uuid7(),
                "category_key": category,
                "action": "block",
                "match": match,
                "value": value,
                "conditions": conditions,
                "label": value,
            }
            for category, match, value, conditions in RULES
        ],
    )

    op.create_table(
        "proctor_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), server_default="open", nullable=False),
        sa.Column("app_version", sa.Text(), server_default="", nullable=False),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        _jsonb("policy", "{}"),
        sa.Column(
            "opened_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        _ts("closed_at"),
        sa.Column("acked_through", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_seq", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        _jsonb("gaps", "[]"),
        _ts("last_heartbeat_at"),
        sa.Column("heartbeats", sa.Integer(), server_default=sa.text("0"), nullable=False),
        _jsonb("last_status", "{}"),
        _jsonb("observed", "{}"),
        _jsonb("nudges", "{}"),
        _ts("watch_at"),
        *_timestamps(),
        sa.CheckConstraint("status IN ('open', 'closed')", name=op.f("ck_proctor_sessions_status")),
        sa.CheckConstraint(
            "acked_through >= 0 AND max_seq >= acked_through",
            name=op.f("ck_proctor_sessions_sequence"),
        ),
        _organization_fk("proctor_sessions"),
        _composite_fk("proctor_sessions", "interview_id", "interviews"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proctor_sessions")),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_proctor_sessions_organization_id_id")
        ),
        sa.UniqueConstraint("interview_id", name=op.f("uq_proctor_sessions_interview_id")),
    )
    op.create_index(
        "ix_proctor_sessions_watch_at",
        "proctor_sessions",
        ["watch_at"],
        postgresql_where=sa.text("status = 'open'"),
    )
    _tenant("proctor_sessions", ["SELECT", "INSERT", "UPDATE"])

    op.create_table(
        "proctor_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("proctor_session_id", sa.Uuid(), nullable=False),
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=True),
        sa.Column("last_seq", sa.BigInteger(), nullable=True),
        sa.Column("origin", sa.Text(), server_default="client", nullable=False),
        sa.Column("event", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        _ts("started_at", nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("ongoing", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("phase", sa.Text(), nullable=True),
        _jsonb("details", "{}"),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("review_status", sa.Text(), server_default="pending", nullable=False),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(_in("severity", SEVERITIES), name=op.f("ck_proctor_events_severity")),
        sa.CheckConstraint("origin IN ('client', 'server')", name=op.f("ck_proctor_events_origin")),
        sa.CheckConstraint(
            _in("review_status", REVIEW_STATUSES), name=op.f("ck_proctor_events_review_status")
        ),
        sa.CheckConstraint(
            f"phase IS NULL OR {_in('phase', PHASES)}", name=op.f("ck_proctor_events_phase")
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name=op.f("ck_proctor_events_duration")
        ),
        _organization_fk("proctor_events"),
        _composite_fk("proctor_events", "proctor_session_id", "proctor_sessions"),
        _composite_fk("proctor_events", "interview_id", "interviews"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proctor_events")),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_proctor_events_organization_id_id")
        ),
    )
    op.create_index(
        "ix_proctor_events_interview_id_started_at",
        "proctor_events",
        ["interview_id", "started_at", "id"],
    )
    op.create_index(
        "ix_proctor_events_session_id_event",
        "proctor_events",
        ["proctor_session_id", "event", "started_at"],
    )
    op.create_index(
        "ix_proctor_events_severity",
        "proctor_events",
        ["organization_id", "severity", "review_status"],
    )
    op.create_index(
        "uq_proctor_events_session_seq",
        "proctor_events",
        ["proctor_session_id", "seq"],
        unique=True,
        postgresql_where=sa.text("seq IS NOT NULL"),
    )
    op.create_index(
        "uq_proctor_events_episode",
        "proctor_events",
        ["proctor_session_id", "event", "started_at"],
        unique=True,
        postgresql_where=sa.text("phase IS NOT NULL AND origin = 'client'"),
    )
    _tenant("proctor_events", ["SELECT", "INSERT", "UPDATE"])

    op.create_table(
        "proctor_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("proctor_session_id", sa.Uuid(), nullable=False),
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("proctor_event_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), server_default="client", nullable=False),
        sa.Column("blob_path", sa.Text(), nullable=True),
        sa.Column("content_type", sa.Text(), nullable=True),
        sa.Column("bytes", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.Text(), nullable=True),
        _ts("window_start"),
        _ts("window_end"),
        _jsonb("ref", "{}"),
        _created(),
        sa.CheckConstraint(_in("kind", EVIDENCE_KINDS), name=op.f("ck_proctor_evidence_kind")),
        sa.CheckConstraint(
            "origin IN ('client', 'server')", name=op.f("ck_proctor_evidence_origin")
        ),
        _organization_fk("proctor_evidence"),
        _composite_fk("proctor_evidence", "proctor_session_id", "proctor_sessions"),
        _composite_fk("proctor_evidence", "proctor_event_id", "proctor_events"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proctor_evidence")),
    )
    op.create_index("ix_proctor_evidence_event_id", "proctor_evidence", ["proctor_event_id"])
    op.create_index("ix_proctor_evidence_session_id", "proctor_evidence", ["proctor_session_id"])
    op.create_index(
        "uq_proctor_evidence_blob",
        "proctor_evidence",
        ["proctor_session_id", "blob_path"],
        unique=True,
        postgresql_where=sa.text("blob_path IS NOT NULL"),
    )
    _tenant("proctor_evidence", ["SELECT", "INSERT", "UPDATE"])

    op.create_table(
        "proctor_event_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("proctor_event_id", sa.Uuid(), nullable=False),
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("previous", sa.Text(), server_default="pending", nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        _created(),
        sa.CheckConstraint(
            "outcome IN ('confirmed', 'false_positive', 'not_relevant')",
            name=op.f("ck_proctor_event_reviews_outcome"),
        ),
        sa.CheckConstraint(
            "length(btrim(reason)) > 0", name=op.f("ck_proctor_event_reviews_reason")
        ),
        _organization_fk("proctor_event_reviews"),
        _composite_fk("proctor_event_reviews", "proctor_event_id", "proctor_events"),
        _composite_fk("proctor_event_reviews", "reviewer_id", "users", ondelete=None),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proctor_event_reviews")),
    )
    op.create_index(
        "ix_proctor_event_reviews_event_id",
        "proctor_event_reviews",
        ["proctor_event_id", "created_at"],
    )
    # Reviews are history: added, never changed.
    _tenant("proctor_event_reviews", ["SELECT", "INSERT"])

    # The watcher lists the open sessions it must look at across organisations, as the
    # interview scheduler lists interviews.
    op.execute(grant_sql("proctor_sessions", ["SELECT"], role=SCHEDULER_ROLE))
    op.execute(
        f"CREATE POLICY proctor_sessions_scheduler ON proctor_sessions FOR SELECT "
        f"TO {SCHEDULER_ROLE} USING (true)"
    )
    op.execute(DUE_SQL)
    op.execute(f"ALTER FUNCTION {DUE_FUNCTION} OWNER TO {SCHEDULER_ROLE}")
    op.execute(f"REVOKE ALL ON FUNCTION {DUE_FUNCTION} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {DUE_FUNCTION} TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {DUE_FUNCTION}")
    op.execute("DROP POLICY IF EXISTS proctor_sessions_scheduler ON proctor_sessions")
    op.drop_table("proctor_event_reviews")
    op.drop_table("proctor_evidence")
    op.drop_table("proctor_events")
    op.drop_table("proctor_sessions")
    op.drop_table("app_rules")
    op.drop_table("app_categories")
