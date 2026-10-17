"""The third eye (SP-13): pairings, and Egress recordings in the recordings table.

- `third_eye_pairings`: one phone paired as an interview's third camera. The phone redeems its
  token (or rejoins with its device secret) before its organisation is known, so the lookup is a
  SECURITY DEFINER function owned by `hirevion_auth`, as the portal's session lookup is (0019).
- `recordings` gains `source` (`desktop` or `egress`), `egress_id` and `started_at`. Egress writes
  whole files (`conversation-audio-N`, `third-eye-N`), so the media worker's two listings (0016)
  are redefined to leave them out: they are neither assembled nor watched for silence.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-12
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from hirevion_core.db.rls import grant_sql, tenant_policy_sql
from hirevion_core.settings import APP_ROLE, AUTH_ROLE, SCHEDULER_ROLE

revision: str = "0020"
down_revision: str | Sequence[str] | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = ("issued", "redeemed", "connected", "disconnected", "revoked")
REVOKE_REASONS = ("replaced", "revoked", "interview-ended")
DESKTOP_TRACK = "^(screen-[1-8]|camera|mic)$"
EGRESS_TRACK = "^(conversation-audio|third-eye)-[1-9][0-9]{0,2}$"

LOOKUP_SQL = """
CREATE FUNCTION auth_third_eye_pairing(p_hash bytea)
RETURNS TABLE (
    pairing_id uuid, organization_id uuid, interview_id uuid, matched text,
    organization_status text
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
AS $$
    SELECT p.id, p.organization_id, p.interview_id,
           CASE WHEN p.token_hash = p_hash THEN 'token' ELSE 'device' END, o.status
    FROM third_eye_pairings p
    JOIN organizations o ON o.id = p.organization_id
    WHERE p.token_hash = p_hash OR p.device_hash = p_hash
$$
"""
LOOKUP = "auth_third_eye_pairing(bytea)"

# 0016's listings, now only for the desktop's tracks.
DUE_ASSEMBLY = "recording_due_assembly(timestamptz, integer, text[])"
LIVE_TRACKS = "recording_live_tracks(timestamptz, integer)"


DUE_ASSEMBLY_SQL = """
CREATE FUNCTION recording_due_assembly(p_now timestamptz, p_limit integer, p_ended text[])
RETURNS TABLE (organization_id uuid, interview_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
AS $$
    SELECT r.organization_id, r.interview_id
    FROM recordings r
    JOIN organizations o ON o.id = r.organization_id AND o.status = 'active'
    JOIN interviews i ON i.organization_id = r.organization_id AND i.id = r.interview_id
    WHERE __SOURCE__((r.status = 'assembly-pending'
           AND (r.next_attempt_at IS NULL OR r.next_attempt_at <= p_now))
       OR (r.status = 'recording'
           AND i.status = ANY(p_ended))
       OR (r.status = 'assembling' AND r.updated_at <= p_now - interval '30 minutes'))
    GROUP BY r.organization_id, r.interview_id
    ORDER BY min(r.ready_at) NULLS FIRST
    LIMIT p_limit
$$
"""


LIVE_TRACKS_SQL = """
CREATE FUNCTION recording_live_tracks(p_now timestamptz, p_limit integer)
RETURNS TABLE (
    organization_id uuid, interview_id uuid, started_at timestamptz, connected_at timestamptz,
    policy jsonb, track text, last_seq integer, last_ended_at timestamptz,
    last_segment_at timestamptz, stalled boolean
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
AS $$
    SELECT i.organization_id, i.id, i.started_at, s.connected_at, i.policy,
           r.track, r.last_seq, r.last_ended_at, r.last_segment_at,
           (r.stalled_since IS NOT NULL)
    FROM interviews i
    JOIN organizations o ON o.id = i.organization_id AND o.status = 'active'
    LEFT JOIN interview_sessions s ON s.interview_id = i.id
    LEFT JOIN recordings r ON r.interview_id = i.id__SOURCE__
    WHERE i.status = 'in_progress' AND i.started_at <= p_now
    ORDER BY i.started_at, i.id, r.track
    LIMIT p_limit
$$
"""


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _ts(name: str, nullable: bool = True) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _created(name: str) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _composite_fk(table: str, column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id", column],
        [f"{target}.organization_id", f"{target}.id"],
        name=op.f(f"fk_{table}_organization_id_{column}_{target}"),
        ondelete="CASCADE",
    )


def _replace_listings(desktop_only: bool) -> None:
    for function, sql in (
        (
            DUE_ASSEMBLY,
            DUE_ASSEMBLY_SQL.replace(
                "__SOURCE__", "r.source = 'desktop' AND " if desktop_only else ""
            ),
        ),
        (
            LIVE_TRACKS,
            LIVE_TRACKS_SQL.replace(
                "__SOURCE__", " AND r.source = 'desktop'" if desktop_only else ""
            ),
        ),
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
        op.execute(sql)
        op.execute(f"ALTER FUNCTION {function} OWNER TO {SCHEDULER_ROLE}")
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO {APP_ROLE}")


def upgrade() -> None:
    table = "third_eye_pairings"
    op.create_table(
        table,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("device_hash", sa.LargeBinary(), nullable=True),
        sa.Column("status", sa.Text(), server_default="issued", nullable=False),
        _ts("expires_at", nullable=False),
        _ts("redeemed_at"),
        _ts("connected_at"),
        _ts("last_seen_at"),
        _ts("disconnected_at"),
        _ts("revoked_at"),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.Column(
            "device", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("video", postgresql.JSONB(), nullable=True),
        sa.Column("reconnects", sa.Integer(), server_default=sa.text("0"), nullable=False),
        _created("created_at"),
        _created("updated_at"),
        sa.CheckConstraint(_in("status", STATUSES), name=op.f(f"ck_{table}_status")),
        sa.CheckConstraint(
            f"revoke_reason IS NULL OR {_in('revoke_reason', REVOKE_REASONS)}",
            name=op.f(f"ck_{table}_revoke_reason"),
        ),
        sa.CheckConstraint(
            "(status = 'revoked') = (revoked_at IS NOT NULL)", name=op.f(f"ck_{table}_revoked")
        ),
        sa.CheckConstraint("reconnects >= 0", name=op.f(f"ck_{table}_reconnects")),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f(f"fk_{table}_organization_id_organizations"),
        ),
        _composite_fk(table, "interview_id", "interviews"),
        _composite_fk(table, "candidate_id", "candidates"),
        _composite_fk(table, "account_id", "candidate_accounts"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("token_hash", name=op.f(f"uq_{table}_token_hash")),
        sa.UniqueConstraint("device_hash", name=op.f(f"uq_{table}_device_hash")),
    )
    op.create_index("ix_third_eye_pairings_interview_id", table, ["interview_id"])
    op.create_index(
        "uq_third_eye_pairings_live",
        table,
        ["interview_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(op.f(f"ix_{table}_organization_id"), table, ["organization_id"])
    for statement in tenant_policy_sql(table):
        op.execute(statement)
    # Pairings are revoked, never deleted; they go with their interview.
    op.execute(grant_sql(table, ["SELECT", "INSERT", "UPDATE"]))
    op.execute(grant_sql(table, ["SELECT"], role=AUTH_ROLE))
    op.execute(
        f"CREATE POLICY {table}_auth_lookup ON {table} FOR SELECT TO {AUTH_ROLE} USING (true)"
    )
    op.execute(LOOKUP_SQL)
    op.execute(f"ALTER FUNCTION {LOOKUP} OWNER TO {AUTH_ROLE}")
    op.execute(f"REVOKE ALL ON FUNCTION {LOOKUP} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {LOOKUP} TO {APP_ROLE}")

    op.add_column(
        "recordings", sa.Column("source", sa.Text(), server_default="desktop", nullable=False)
    )
    op.add_column("recordings", sa.Column("egress_id", sa.Text(), nullable=True))
    op.add_column("recordings", _ts("started_at"))
    op.create_unique_constraint(op.f("uq_recordings_egress_id"), "recordings", ["egress_id"])
    op.create_check_constraint(
        op.f("ck_recordings_source"), "recordings", _in("source", ("desktop", "egress"))
    )
    op.drop_constraint(op.f("ck_recordings_track"), "recordings", type_="check")
    op.create_check_constraint(
        op.f("ck_recordings_track"),
        "recordings",
        f"(source = 'desktop' AND track ~ '{DESKTOP_TRACK}') "
        f"OR (source = 'egress' AND track ~ '{EGRESS_TRACK}')",
    )
    _replace_listings(desktop_only=True)


def downgrade() -> None:
    _replace_listings(desktop_only=False)
    op.execute("DELETE FROM recordings WHERE source = 'egress'")
    op.drop_constraint(op.f("ck_recordings_track"), "recordings", type_="check")
    op.create_check_constraint(
        op.f("ck_recordings_track"), "recordings", f"track ~ '{DESKTOP_TRACK}'"
    )
    op.drop_constraint(op.f("ck_recordings_source"), "recordings", type_="check")
    op.drop_constraint(op.f("uq_recordings_egress_id"), "recordings", type_="unique")
    op.drop_column("recordings", "started_at")
    op.drop_column("recordings", "egress_id")
    op.drop_column("recordings", "source")
    op.execute(f"DROP FUNCTION IF EXISTS {LOOKUP}")
    op.drop_table("third_eye_pairings")
