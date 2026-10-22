"""The interview engine's tables (SP-09): system checks, consents and accommodations before the
interview; the engine's checkpoint, the questions asked, the answers given and workspace snapshots
during it; and the two-sided transcript with its artifacts. Transcript segments are partitioned
by month like the other high-volume tables. Organisations gain their interview briefing
(instructions and FAQ), interviews the time they were interrupted, and the scheduler abandons
interviews interrupted for longer than their resume policy's grace.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-09
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from hirevion_core.db.rls import grant_sql, tenant_policy_sql

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 0013's listing plus interviews interrupted for longer than their grace (SP-09).
DUE_SQL = """
CREATE OR REPLACE FUNCTION scheduler_due_interviews(
    p_now timestamptz, p_lead interval, p_limit integer
)
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
       OR (i.status = 'interrupted' AND i.interrupted_at IS NOT NULL
           AND i.interrupted_at + make_interval(
               secs => coalesce((i.policy -> 'resume' ->> 'grace_seconds')::integer, 300)
           ) <= p_now)
    ORDER BY i.expires_at
    LIMIT p_limit
$$
"""

PREVIOUS_DUE_SQL = """
CREATE OR REPLACE FUNCTION scheduler_due_interviews(
    p_now timestamptz, p_lead interval, p_limit integer
)
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

CHECK_STATUSES = ("requested", "approved", "declined")
MODES = ("voice", "text")
KINDS = ("introduction", "main", "follow_up", "coding", "final")
SOURCES = ("pinned", "library", "generated", "resume", "follow_up", "faq", "system")
QUESTION_STATES = ("asked", "answered", "timed_out", "skipped")
QUALITIES = ("strong", "partial", "weak", "no_answer")


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


def _jsonb(name: str, default: str) -> sa.Column[object]:
    return sa.Column(
        # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
        # (`default` is a constant of this migration: "{}" or "[]")
        name,
        postgresql.JSONB(),
        server_default=sa.text(f"'{default}'::jsonb"),
        nullable=False,
    )


def _texts(name: str) -> sa.Column[object]:
    return sa.Column(
        name, postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False
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


def _tenant(table: str, privileges: list[str], *, index: bool = True) -> None:
    if index:
        op.create_index(op.f(f"ix_{table}_organization_id"), table, ["organization_id"])
    for statement in tenant_policy_sql(table):
        op.execute(statement)
    op.execute(grant_sql(table, privileges))


def upgrade() -> None:
    op.add_column(
        "organization_settings",
        _jsonb("interview_briefing", "{}"),
    )
    op.add_column("interviews", _ts("interrupted_at"))

    op.create_table(
        "system_check_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("app_version", sa.Text(), nullable=False),
        sa.Column("os", sa.Text(), nullable=False),
        _jsonb("results", "[]"),
        sa.Column("passed", sa.Boolean(), nullable=False),
        _texts("failed_mandatory"),
        _created(),
        _organization_fk("system_check_results"),
        _composite_fk("system_check_results", "interview_id", "interviews"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_system_check_results")),
    )
    op.create_index(
        "ix_system_check_results_interview_id", "system_check_results", ["interview_id"]
    )
    # Records of what the desktop reported: added, never changed.
    _tenant("system_check_results", ["SELECT", "INSERT"])

    op.create_table(
        "consents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("notice_version", sa.Text(), nullable=False),
        _jsonb("items", "[]"),
        sa.Column("complete", sa.Boolean(), nullable=False),
        _texts("missing"),
        sa.Column("ip", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        _created(),
        _organization_fk("consents"),
        _composite_fk("consents", "interview_id", "interviews"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consents")),
    )
    op.create_index("ix_consents_interview_id", "consents", ["interview_id"])
    _tenant("consents", ["SELECT", "INSERT"])

    op.create_table(
        "accommodations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("kinds", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("note", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.Text(), server_default="requested", nullable=False),
        _texts("approved_kinds"),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        _ts("decided_at"),
        *_timestamps(),
        sa.CheckConstraint(_in("status", CHECK_STATUSES), name=op.f("ck_accommodations_status")),
        _organization_fk("accommodations"),
        _composite_fk("accommodations", "interview_id", "interviews"),
        sa.ForeignKeyConstraint(
            ["organization_id", "decided_by"],
            ["users.organization_id", "users.id"],
            name=op.f("fk_accommodations_organization_id_decided_by_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_accommodations")),
    )
    op.create_index("ix_accommodations_interview_id", "accommodations", ["interview_id"])
    _tenant("accommodations", ["SELECT", "INSERT", "UPDATE"])

    op.create_table(
        "interview_sessions",
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.Text(), server_default="voice", nullable=False),
        sa.Column("room", sa.Text(), nullable=False),
        _jsonb("state", "{}"),
        sa.Column("state_seq", sa.Integer(), server_default=sa.text("0"), nullable=False),
        _ts("started_at", nullable=False),
        _ts("deadline_at", nullable=False),
        sa.Column("paused_seconds", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("interruptions", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("reconnects", sa.Integer(), server_default=sa.text("0"), nullable=False),
        _ts("connected_at"),
        sa.Column("system_check_id", sa.Uuid(), nullable=True),
        sa.Column("consent_id", sa.Uuid(), nullable=True),
        sa.Column("agent_dispatch_id", sa.Text(), nullable=True),
        _ts("ended_at"),
        *_timestamps(),
        sa.CheckConstraint(_in("mode", MODES), name=op.f("ck_interview_sessions_mode")),
        sa.CheckConstraint(
            "paused_seconds >= 0", name=op.f("ck_interview_sessions_paused_seconds")
        ),
        _organization_fk("interview_sessions"),
        _composite_fk("interview_sessions", "interview_id", "interviews"),
        sa.PrimaryKeyConstraint("interview_id", name=op.f("pk_interview_sessions")),
    )
    _tenant("interview_sessions", ["SELECT", "INSERT", "UPDATE"])

    op.create_table(
        "interview_questions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("skill", sa.Text(), nullable=True),
        sa.Column("topic", sa.Text(), nullable=True),
        sa.Column("difficulty", sa.Text(), nullable=True),
        sa.Column("type", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        _jsonb("source_ref", "{}"),
        _texts("expected_concepts"),
        sa.Column("time_limit_seconds", sa.Integer(), nullable=True),
        sa.Column("workspace", sa.Text(), server_default="none", nullable=False),
        _texts("languages"),
        sa.Column("status", sa.Text(), server_default="asked", nullable=False),
        _ts("asked_at", nullable=False),
        _ts("closed_at"),
        sa.CheckConstraint(_in("kind", KINDS), name=op.f("ck_interview_questions_kind")),
        sa.CheckConstraint(_in("source", SOURCES), name=op.f("ck_interview_questions_source")),
        sa.CheckConstraint(
            _in("status", QUESTION_STATES), name=op.f("ck_interview_questions_status")
        ),
        _organization_fk("interview_questions"),
        _composite_fk("interview_questions", "interview_id", "interviews"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_interview_questions")),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_interview_questions_organization_id_id")
        ),
        sa.UniqueConstraint(
            "interview_id", "position", name=op.f("uq_interview_questions_interview_id_position")
        ),
    )
    _tenant("interview_questions", ["SELECT", "INSERT", "UPDATE"])

    op.create_table(
        "interview_answers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        _ts("started_at"),
        _ts("ended_at", nullable=False),
        sa.Column("late", sa.Boolean(), server_default=sa.false(), nullable=False),
        _jsonb("analysis", "{}"),
        sa.Column("quality", sa.Text(), nullable=True),
        _texts("flags"),
        _created(),
        sa.CheckConstraint(_in("mode", MODES), name=op.f("ck_interview_answers_mode")),
        sa.CheckConstraint(
            f"quality IS NULL OR {_in('quality', QUALITIES)}",
            name=op.f("ck_interview_answers_quality"),
        ),
        _organization_fk("interview_answers"),
        _composite_fk("interview_answers", "interview_id", "interviews"),
        _composite_fk("interview_answers", "question_id", "interview_questions"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_interview_answers")),
    )
    op.create_index("ix_interview_answers_interview_id", "interview_answers", ["interview_id"])
    op.create_index("ix_interview_answers_question_id", "interview_answers", ["question_id"])
    _tenant("interview_answers", ["SELECT", "INSERT"])

    op.create_table(
        "workspace_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        _created(),
        sa.CheckConstraint(
            "kind IN ('code', 'whiteboard')", name=op.f("ck_workspace_snapshots_kind")
        ),
        _organization_fk("workspace_snapshots"),
        _composite_fk("workspace_snapshots", "interview_id", "interviews"),
        _composite_fk("workspace_snapshots", "question_id", "interview_questions"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_snapshots")),
    )
    op.create_index("ix_workspace_snapshots_interview_id", "workspace_snapshots", ["interview_id"])
    _tenant("workspace_snapshots", ["SELECT", "INSERT"])

    op.create_table(
        "transcripts",
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("segment_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        _jsonb("artifacts", "{}"),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('pending', 'ready', 'failed')", name=op.f("ck_transcripts_status")
        ),
        _organization_fk("transcripts"),
        _composite_fk("transcripts", "interview_id", "interviews"),
        sa.PrimaryKeyConstraint("interview_id", name=op.f("pk_transcripts")),
    )
    _tenant("transcripts", ["SELECT", "INSERT", "UPDATE"])

    op.create_table(
        "transcript_segments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("speaker", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.CheckConstraint(
            "speaker IN ('ai', 'candidate')", name=op.f("ck_transcript_segments_speaker")
        ),
        sa.CheckConstraint(
            "start_ms >= 0 AND end_ms >= start_ms", name=op.f("ck_transcript_segments_times")
        ),
        _organization_fk("transcript_segments"),
        _composite_fk("transcript_segments", "interview_id", "interviews"),
        sa.PrimaryKeyConstraint("id", "occurred_at", name=op.f("pk_transcript_segments")),
        postgresql_partition_by="RANGE (occurred_at)",
    )
    op.create_index(
        "ix_transcript_segments_interview_id_seq", "transcript_segments", ["interview_id", "seq"]
    )
    op.execute("CREATE TABLE transcript_segments_default PARTITION OF transcript_segments DEFAULT")
    _tenant("transcript_segments", ["SELECT", "INSERT"])

    op.execute(DUE_SQL)


def downgrade() -> None:
    op.execute(PREVIOUS_DUE_SQL)
    op.drop_table("transcript_segments")
    op.drop_table("transcripts")
    op.drop_table("workspace_snapshots")
    op.drop_table("interview_answers")
    op.drop_table("interview_questions")
    op.drop_table("interview_sessions")
    op.drop_table("accommodations")
    op.drop_table("consents")
    op.drop_table("system_check_results")
    op.drop_column("interviews", "interrupted_at")
    op.drop_column("organization_settings", "interview_briefing")
