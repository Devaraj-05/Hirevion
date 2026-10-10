"""The recording pipeline's tables (SP-12; PRD §50, §51, §85): the segments the desktop uploads,
and the recording each track assembles into."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hirevion_core.db.base import Base, IdMixin, TenantMixin, TimestampMixin

SEGMENT_STATES = ("requested", "uploaded", "acknowledged")
RECORDING_STATUSES = ("recording", "assembly-pending", "assembling", "assembled", "failed")
CONTAINERS = ("mp4", "webm")
CODECS = ("h264", "vp8", "opus", "aac")
# Mirrors `hirevion_core.recordings.tracks` and the contract's limits.
TRACK_PATTERN = "^(screen-[1-8]|camera|mic)$"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _interview_fk() -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["organization_id", "interview_id"],
        ["interviews.organization_id", "interviews.id"],
        ondelete="CASCADE",
    )


class RecordingSegment(IdMixin, TenantMixin, TimestampMixin, Base):
    """One 10-second segment of one track, from the upload URL being asked for until the server
    has read the blob and checked its size and SHA-256 (`acknowledged`)."""

    __tablename__ = "recording_segments"
    __table_args__ = (
        _interview_fk(),
        UniqueConstraint("interview_id", "track", "seq"),
        CheckConstraint(f"track ~ '{TRACK_PATTERN}'", name="track"),
        CheckConstraint("seq >= 0", name="seq"),
        CheckConstraint("duration_ms > 0 AND duration_ms <= 60000", name="duration"),
        CheckConstraint("bytes > 0 AND bytes <= 50000000", name="bytes"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256"),
        CheckConstraint(_in("container", CONTAINERS), name="container"),
        CheckConstraint(_in("codec", CODECS), name="codec"),
        CheckConstraint(_in("state", SEGMENT_STATES), name="state"),
        Index("ix_recording_segments_interview_id_state", "interview_id", "state"),
    )

    interview_id: Mapped[UUID]
    track: Mapped[str] = mapped_column(Text)
    seq: Mapped[int] = mapped_column(Integer)
    # When the segment started, in server time (the desktop keeps a clock offset), and how long.
    started_at: Mapped[datetime]
    duration_ms: Mapped[int] = mapped_column(Integer)
    bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(Text)
    container: Mapped[str] = mapped_column(Text)
    codec: Mapped[str] = mapped_column(Text)
    blob_path: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text, server_default="requested")
    attempts: Mapped[int] = mapped_column(Integer, server_default=sql_text("0"))
    # The last time an upload URL was issued for it.
    requested_at: Mapped[datetime] = mapped_column(server_default=func.now())
    uploaded_at: Mapped[datetime | None]
    acknowledged_at: Mapped[datetime | None]


class Recording(IdMixin, TenantMixin, TimestampMixin, Base):
    """One track of one interview: what has arrived, whether it stalled, and the assembled file."""

    __tablename__ = "recordings"
    __table_args__ = (
        _interview_fk(),
        UniqueConstraint("interview_id", "track"),
        CheckConstraint(f"track ~ '{TRACK_PATTERN}'", name="track"),
        CheckConstraint(_in("status", RECORDING_STATUSES), name="status"),
        Index("ix_recordings_status_next_attempt_at", "status", "next_attempt_at"),
    )

    interview_id: Mapped[UUID]
    track: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="recording")
    # The lowest and highest segment numbers that have been asked for.
    first_seq: Mapped[int | None] = mapped_column(Integer)
    last_seq: Mapped[int | None] = mapped_column(Integer)
    # When a segment of the track last arrived (server time), and where the latest one ended.
    last_segment_at: Mapped[datetime | None]
    last_ended_at: Mapped[datetime | None]
    # Set while the track is silent for longer than the interview's policy allows.
    stalled_since: Mapped[datetime | None]
    gaps: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=sql_text("'[]'::jsonb")
    )
    # Assembly: asked for when the interview ends; retried with a backoff.
    ready_at: Mapped[datetime | None]
    attempts: Mapped[int] = mapped_column(Integer, server_default=sql_text("0"))
    next_attempt_at: Mapped[datetime | None]
    note: Mapped[str | None] = mapped_column(Text)
    container: Mapped[str | None] = mapped_column(Text)
    blob_path: Mapped[str | None] = mapped_column(Text)
    timeline_path: Mapped[str | None] = mapped_column(Text)
    assembled_bytes: Mapped[int | None] = mapped_column(BigInteger)
    assembled_sha256: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    assembled_at: Mapped[datetime | None]
