"""The recording pipeline's tables (SP-12, PRD §50, §51, §85): the segments the desktop uploads
(one row per interview, track and segment number, from the upload URL being asked for until the
server has verified the blob) and one recording per interview and track, which the media worker
assembles into a single file with a timeline map.

The media worker has to find work across organisations: tracks to assemble, and the tracks of
interviews in progress to watch for silence. Two listing functions belong to the scheduler's
role (0013), which can't log in, doesn't bypass row-level security and reads only what they need.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-10
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from hirevion_core.db.rls import grant_sql, tenant_policy_sql
from hirevion_core.settings import APP_ROLE, SCHEDULER_ROLE

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEGMENT_STATES = ("requested", "uploaded", "acknowledged")
RECORDING_STATUSES = ("recording", "assembly-pending", "assembling", "assembled", "failed")
CONTAINERS = ("mp4", "webm")
CODECS = ("h264", "vp8", "opus", "aac")
TRACK_PATTERN = "^(screen-[1-8]|camera|mic)$"

# One row per interview that has tracks to assemble now (its recordings are `assembly-pending`
# and not backing off), in active organisations. The caller handles each in its tenant's
# transaction and re-checks it there.
DUE_ASSEMBLY_SQL = """
CREATE FUNCTION recording_due_assembly(p_now timestamptz, p_limit integer)
RETURNS TABLE (organization_id uuid, interview_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
AS $$
    SELECT r.organization_id, r.interview_id
    FROM recordings r
    JOIN organizations o ON o.id = r.organization_id AND o.status = 'active'
    WHERE r.status = 'assembly-pending'
      AND (r.next_attempt_at IS NULL OR r.next_attempt_at <= p_now)
    GROUP BY r.organization_id, r.interview_id
    ORDER BY min(r.ready_at) NULLS FIRST
    LIMIT p_limit
$$
"""

# The tracks of every interview in progress, with what the continuity rules need: when it
# started and the candidate last connected, its policy, and per track where it stopped. An
# interview whose tracks haven't produced anything yet has one row with a null track.
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
    LEFT JOIN recordings r ON r.interview_id = i.id
    WHERE i.status = 'in_progress' AND i.started_at <= p_now
    ORDER BY i.started_at, i.id, r.track
    LIMIT p_limit
$$
"""

RECORDING_FUNCTIONS = (
    "recording_due_assembly(timestamptz, integer)",
    "recording_live_tracks(timestamptz, integer)",
)
SCHEDULER_TABLES = ("recordings", "interview_sessions")


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


def _ts(name: str, nullable: bool = True) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _organization_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id"],
        ["organizations.id"],
        name=op.f(f"fk_{table}_organization_id_organizations"),
    )


def _interview_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id", "interview_id"],
        ["interviews.organization_id", "interviews.id"],
        name=op.f(f"fk_{table}_organization_id_interview_id_interviews"),
        ondelete="CASCADE",
    )


def _tenant(table: str, privileges: list[str]) -> None:
    op.create_index(op.f(f"ix_{table}_organization_id"), table, ["organization_id"])
    for statement in tenant_policy_sql(table):
        op.execute(statement)
    op.execute(grant_sql(table, privileges))


def upgrade() -> None:
    op.create_table(
        "recording_segments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("track", sa.Text(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        _ts("started_at", nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("container", sa.Text(), nullable=False),
        sa.Column("codec", sa.Text(), nullable=False),
        sa.Column("blob_path", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), server_default="requested", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        _ts("uploaded_at"),
        _ts("acknowledged_at"),
        *_timestamps(),
        sa.CheckConstraint(f"track ~ '{TRACK_PATTERN}'", name=op.f("ck_recording_segments_track")),
        sa.CheckConstraint("seq >= 0", name=op.f("ck_recording_segments_seq")),
        sa.CheckConstraint(
            "duration_ms > 0 AND duration_ms <= 60000", name=op.f("ck_recording_segments_duration")
        ),
        sa.CheckConstraint(
            "bytes > 0 AND bytes <= 50000000", name=op.f("ck_recording_segments_bytes")
        ),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_recording_segments_sha256")),
        sa.CheckConstraint(
            _in("container", CONTAINERS), name=op.f("ck_recording_segments_container")
        ),
        sa.CheckConstraint(_in("codec", CODECS), name=op.f("ck_recording_segments_codec")),
        sa.CheckConstraint(_in("state", SEGMENT_STATES), name=op.f("ck_recording_segments_state")),
        _organization_fk("recording_segments"),
        _interview_fk("recording_segments"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recording_segments")),
        sa.UniqueConstraint(
            "interview_id",
            "track",
            "seq",
            name=op.f("uq_recording_segments_interview_id_track_seq"),
        ),
    )
    op.create_index(
        op.f("ix_recording_segments_interview_id_state"),
        "recording_segments",
        ["interview_id", "state"],
    )
    # Segments are never deleted by the application; they go with their interview.
    _tenant("recording_segments", ["SELECT", "INSERT", "UPDATE"])

    op.create_table(
        "recordings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("track", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="recording", nullable=False),
        sa.Column("first_seq", sa.Integer(), nullable=True),
        sa.Column("last_seq", sa.Integer(), nullable=True),
        _ts("last_segment_at"),
        _ts("last_ended_at"),
        _ts("stalled_since"),
        sa.Column(
            "gaps",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        _ts("ready_at"),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        _ts("next_attempt_at"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("container", sa.Text(), nullable=True),
        sa.Column("blob_path", sa.Text(), nullable=True),
        sa.Column("timeline_path", sa.Text(), nullable=True),
        sa.Column("assembled_bytes", sa.BigInteger(), nullable=True),
        sa.Column("assembled_sha256", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        _ts("assembled_at"),
        *_timestamps(),
        sa.CheckConstraint(f"track ~ '{TRACK_PATTERN}'", name=op.f("ck_recordings_track")),
        sa.CheckConstraint(_in("status", RECORDING_STATUSES), name=op.f("ck_recordings_status")),
        _organization_fk("recordings"),
        _interview_fk("recordings"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recordings")),
        sa.UniqueConstraint("interview_id", "track", name=op.f("uq_recordings_interview_id_track")),
    )
    op.create_index(
        op.f("ix_recordings_status_next_attempt_at"),
        "recordings",
        ["status", "next_attempt_at"],
    )
    _tenant("recordings", ["SELECT", "INSERT", "UPDATE"])

    # The media worker's listings (the 0013 pattern: the role reads, row-level security allows
    # it to read only for these tables, and the functions are all it can run).
    for table in SCHEDULER_TABLES:
        op.execute(grant_sql(table, ["SELECT"], role=SCHEDULER_ROLE))
        op.execute(
            f"CREATE POLICY {table}_scheduler ON {table} FOR SELECT TO {SCHEDULER_ROLE} "
            "USING (true)"
        )
    op.execute(DUE_ASSEMBLY_SQL)
    op.execute(LIVE_TRACKS_SQL)
    for function in RECORDING_FUNCTIONS:
        op.execute(f"ALTER FUNCTION {function} OWNER TO {SCHEDULER_ROLE}")
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO {APP_ROLE}")


def downgrade() -> None:
    for function in RECORDING_FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
    for table in SCHEDULER_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_scheduler ON {table}")
        op.execute(f"REVOKE SELECT ON {table} FROM {SCHEDULER_ROLE}")  # noqa: S608 (a constant)
    op.drop_table("recordings")
    op.drop_table("recording_segments")
