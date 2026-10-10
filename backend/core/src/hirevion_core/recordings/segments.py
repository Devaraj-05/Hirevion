"""Segment uploads and their acknowledgement (SP-12; `docs/api/contracts/recordings.md`).

A segment is asked for (`request_upload`: a write-only URL for one blob), uploaded by the
desktop straight to storage, and acknowledged (`acknowledge`: the server reads the blob and
checks its size and SHA-256 against what was declared). Only then does the desktop delete its
copy. `recovery` tells it what the server holds after a crash.

`seq` only ever increases per track but may skip numbers; a later `seq` is never refused, and
the skipped numbers are reported as gaps (a `recording.gap` event, and `missing` in `recovery`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.db.session import Database
from hirevion_core.ids import uuid7
from hirevion_core.models import Interview, Recording, RecordingSegment
from hirevion_core.outbox import publish_event
from hirevion_core.recordings import tracks
from hirevion_core.recordings.continuity import gap_payload
from hirevion_core.storage.paths import BlobPath, interview_blob
from hirevion_core.storage.service import UPLOAD_TTL

GAP_TOPIC = "recording.gap"
# Statuses in which an interview's recording is over: late segments reopen the assembly.
ENDED_STATUSES = ("completed", "evaluating", "evaluated", "abandoned", "cancelled", "expired")


class Refused(Exception):
    """A request the contract answers with a problem: `status`, a `code` the desktop branches
    on, and extra members for the body."""

    def __init__(self, status: int, code: str, title: str, **extra: Any) -> None:
        super().__init__(f"{status} {code}")
        self.status = status
        self.code = code
        self.title = title
        self.extra = extra


class UploadSigner(Protocol):
    def upload_url(
        self, organization_id: UUID, path: BlobPath, expires: timedelta = ...
    ) -> str: ...


class BlobReader(Protocol):
    async def digest(self, path: BlobPath) -> tuple[int, str] | None: ...


class SegmentStore(UploadSigner, BlobReader, Protocol):
    """What the segment routes need of blob storage (`StorageService` in the app)."""


@dataclass(frozen=True, slots=True)
class SegmentDeclaration:
    """What the desktop says the segment is, before uploading it."""

    interview_id: UUID
    track: str
    seq: int
    started_at: datetime
    duration_ms: int
    bytes: int
    sha256: str
    container: str
    codec: str


@dataclass(frozen=True, slots=True)
class UploadGrant:
    segment_id: UUID
    upload_url: str
    expires_at: datetime
    headers: dict[str, str]


@dataclass(frozen=True, slots=True)
class StatusNotice:
    """A `RECORDING_STATUS` event for the interview's realtime stream, to publish once the
    transaction that produced it has committed."""

    interview_id: UUID
    data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class TrackRecovery:
    acknowledged_through: int | None
    missing: list[int]


def blob_path(row: RecordingSegment) -> BlobPath:
    return BlobPath(row.organization_id, row.blob_path.split("/", 1)[1])


def check_declaration(interview: Interview, declared: SegmentDeclaration) -> None:
    """The contract's rules, in the order a desktop would want to hear about them."""
    if declared.bytes > tracks.MAX_SEGMENT_BYTES:
        raise Refused(413, "segment-too-large", "A segment is at most 50,000,000 bytes")
    if declared.duration_ms > tracks.MAX_SEGMENT_MS:
        raise Refused(422, "segment-too-long", "A segment is at most 60 seconds long")
    if interview.started_at is None:
        raise Refused(409, "interview-not-started", "The interview hasn't started")
    if not tracks.is_recorded(interview.policy, declared.track):
        raise Refused(422, "track-not-recorded", "This interview doesn't record that track")
    if not tracks.format_allowed(declared.track, declared.container, declared.codec):
        raise Refused(422, "unsupported-format", "That container and codec aren't accepted here")


async def lock_recording(session: AsyncSession, interview: Interview, track: str) -> Recording:
    await session.execute(
        insert(Recording)
        .values(
            id=uuid7(),
            organization_id=interview.organization_id,
            interview_id=interview.id,
            track=track,
        )
        .on_conflict_do_nothing(constraint="uq_recordings_interview_id_track")
    )
    return await session.scalar(
        select(Recording)
        .where(Recording.interview_id == interview.id, Recording.track == track)
        .with_for_update()
        .execution_options(populate_existing=True)
    )  # type: ignore[return-value]


async def acknowledged_through(session: AsyncSession, interview_id: UUID, track: str) -> int | None:
    return await session.scalar(
        select(func.max(RecordingSegment.seq)).where(
            RecordingSegment.interview_id == interview_id,
            RecordingSegment.track == track,
            RecordingSegment.state == "acknowledged",
        )
    )


def _status_notice(recording: Recording, status: str, through: int | None) -> StatusNotice:
    return StatusNotice(
        recording.interview_id,
        {
            "track": recording.track,
            "status": status,
            "last_seq": recording.last_seq,
            "acknowledged_through": through,
        },
    )


async def request_upload(
    session: AsyncSession,
    storage: UploadSigner,
    interview: Interview,
    declared: SegmentDeclaration,
    *,
    now: datetime,
) -> tuple[UploadGrant, list[StatusNotice]]:
    """A write-only URL for one segment's blob. Asking again for the same `(interview, track,
    seq)` gives the same `segment_id` and a fresh URL; an acknowledged segment is `409`."""
    check_declaration(interview, declared)
    folder = tracks.folder(declared.track)
    path = interview_blob(
        interview.organization_id,
        interview.id,
        folder,
        tracks.segment_filename(declared.track, declared.seq, declared.container),
    )
    # Everything for one track serialises on its recording row, so the continuity bookkeeping
    # below never races another segment of the same track.
    recording = await lock_recording(session, interview, declared.track)
    inserted = await session.scalar(
        insert(RecordingSegment)
        .values(
            id=uuid7(),
            organization_id=interview.organization_id,
            interview_id=interview.id,
            track=declared.track,
            seq=declared.seq,
            started_at=declared.started_at,
            duration_ms=declared.duration_ms,
            bytes=declared.bytes,
            sha256=declared.sha256,
            container=declared.container,
            codec=declared.codec,
            blob_path=str(path),
            requested_at=now,
        )
        .on_conflict_do_nothing(constraint="uq_recording_segments_interview_id_track_seq")
        .returning(RecordingSegment.id)
    )
    segment = await session.scalar(
        select(RecordingSegment)
        .where(
            RecordingSegment.interview_id == interview.id,
            RecordingSegment.track == declared.track,
            RecordingSegment.seq == declared.seq,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if segment is None:  # the insert above or another request's made it; it can't be gone
        raise RuntimeError("the segment row vanished")
    if segment.state == "acknowledged":
        raise Refused(
            409,
            "segment-acknowledged",
            "The segment is already acknowledged",
            segment_id=str(segment.id),
        )
    if inserted is None:
        # A retry. If the desktop now declares other bytes, the new declaration replaces the old.
        segment.started_at = declared.started_at
        segment.duration_ms = declared.duration_ms
        segment.bytes = declared.bytes
        segment.sha256 = declared.sha256
        segment.container = declared.container
        segment.codec = declared.codec
        segment.blob_path = str(path)
        segment.state = "requested"
        segment.requested_at = now

    notices = await _continuity(
        session, interview, recording, segment, is_new=inserted is not None, now=now
    )
    return (
        UploadGrant(
            segment_id=segment.id,
            upload_url=storage.upload_url(interview.organization_id, path),
            expires_at=now + UPLOAD_TTL,
            headers={
                "x-ms-blob-type": "BlockBlob",
                "Content-Type": tracks.content_type(declared.track, declared.container),
            },
        ),
        notices,
    )


async def _continuity(
    session: AsyncSession,
    interview: Interview,
    recording: Recording,
    segment: RecordingSegment,
    *,
    is_new: bool,
    now: datetime,
) -> list[StatusNotice]:
    """Notes the segment's arrival on its recording and raises what that ends or reveals: a
    stall closing, or numbers that were skipped."""
    previous_last = recording.last_seq
    expected = 0 if previous_last is None else previous_last + 1
    started = interview.started_at or now
    from_time = recording.last_ended_at or started
    notices: list[StatusNotice] = []
    if recording.stalled_since is not None:
        await publish_event(
            session,
            interview.organization_id,
            GAP_TOPIC,
            gap_payload(
                interview.id,
                recording.track,
                kind="stalled",
                state="closed",
                from_seq=expected,
                to_seq=max(segment.seq - 1, expected - 1),
                from_time=from_time,
                to_time=segment.started_at,
                resumed_at=now,
            ),
            key=str(interview.id),
        )
        recording.stalled_since = None
        notices.append(
            _status_notice(
                recording,
                "recording",
                await acknowledged_through(session, interview.id, recording.track),
            )
        )
    elif is_new and segment.seq > expected:
        await publish_event(
            session,
            interview.organization_id,
            GAP_TOPIC,
            gap_payload(
                interview.id,
                recording.track,
                kind="skipped",
                state="closed",
                from_seq=expected,
                to_seq=segment.seq - 1,
                from_time=from_time,
                to_time=segment.started_at,
            ),
            key=str(interview.id),
        )
    if previous_last is None:
        notices.append(_status_notice(recording, "recording", None))
    recording.first_seq = (
        segment.seq if recording.first_seq is None else min(recording.first_seq, segment.seq)
    )
    if previous_last is None or segment.seq >= previous_last:
        recording.last_seq = segment.seq
        recording.last_ended_at = segment.started_at + timedelta(milliseconds=segment.duration_ms)
    recording.last_segment_at = now
    return notices


async def acknowledge(
    db: Database,
    store: BlobReader,
    organization_id: UUID,
    interview_id: UUID,
    segment_id: UUID,
    declared_sha256: str,
    *,
    now: datetime,
) -> None:
    """Reads the segment's blob and checks its size and SHA-256 against the declaration. The
    blob is read outside any transaction, so a slow download never holds a connection."""
    async with db.tenant(organization_id) as session:
        segment = await session.get(RecordingSegment, segment_id)
        # Another interview's segment looks like one that doesn't exist.
        if segment is None or segment.interview_id != interview_id:
            raise Refused(404, "segment-not-found", "No such segment")
        if declared_sha256 != segment.sha256:
            raise Refused(422, "hash-mismatch", "The hash isn't the one declared for this segment")
        if segment.state == "acknowledged":
            return
        path, size = blob_path(segment), segment.bytes
    found = await store.digest(path)
    if found is None:
        raise Refused(404, "blob-missing", "The segment isn't in storage; upload it again")
    verified = found == (size, declared_sha256)
    async with db.tenant(organization_id) as session:
        segment = await session.get_one(RecordingSegment, segment_id, with_for_update=True)
        if segment.state == "acknowledged":
            return
        # A new declaration since the check (a retry) makes this result stale.
        verified = verified and (segment.bytes, segment.sha256) == (size, declared_sha256)
        segment.uploaded_at = now
        if verified:
            segment.state = "acknowledged"
            segment.acknowledged_at = now
            await _reopen_assembly(session, segment, now)
        else:
            segment.state = "uploaded"  # in storage, but not what was declared
            segment.attempts += 1
    if not verified:
        raise Refused(422, "hash-mismatch", "The uploaded blob doesn't match; upload it again")


async def _reopen_assembly(session: AsyncSession, segment: RecordingSegment, now: datetime) -> None:
    """A segment acknowledged after its interview ended belongs in the assembled file: queue the
    track again."""
    interview = await session.get_one(Interview, segment.interview_id)
    if interview.status not in ENDED_STATUSES:
        return
    recording = await session.scalar(
        select(Recording)
        .where(Recording.interview_id == segment.interview_id, Recording.track == segment.track)
        .with_for_update()
    )
    if recording is not None and recording.status != "assembly-pending":
        recording.status = "assembly-pending"
        recording.ready_at = now
        recording.attempts = 0
        recording.next_attempt_at = None
        recording.note = None


async def recovery(session: AsyncSession, interview: Interview) -> dict[str, TrackRecovery]:
    """Per track: the highest acknowledged `seq` (None if there is none yet) and every `seq`
    below it that isn't acknowledged, skipped numbers included."""
    rows = (
        await session.execute(
            select(RecordingSegment.track, RecordingSegment.seq).where(
                RecordingSegment.interview_id == interview.id,
                RecordingSegment.state == "acknowledged",
            )
        )
    ).all()
    acknowledged: dict[str, set[int]] = {t: set() for t in tracks.expected_tracks(interview.policy)}
    for track, seq in rows:
        acknowledged.setdefault(track, set()).add(seq)
    for track in (
        await session.scalars(select(Recording.track).where(Recording.interview_id == interview.id))
    ).all():
        acknowledged.setdefault(track, set())
    result: dict[str, TrackRecovery] = {}
    for track in sorted(acknowledged, key=tracks.track_order):
        seqs = acknowledged[track]
        through = max(seqs) if seqs else None
        missing = [] if through is None else [n for n in range(through) if n not in seqs]
        result[track] = TrackRecovery(through, missing)
    return result
