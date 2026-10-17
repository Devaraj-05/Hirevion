"""Assembling a track's segments into one file with a timeline map (SP-12's media worker).

Once an interview is over and a track's segments are acknowledged (or have stopped arriving), the
acknowledged segments are downloaded, checked against the SHA-256 they were acknowledged with,
joined with ffmpeg's concat demuxer without re-encoding, and uploaded with the timeline map
(`timeline.py`). The recording row says what became of it:

    recording -> assembly-pending -> assembling -> assembled | failed

`assembly-pending` is also where a track waits when ffmpeg isn't installed (the worker logs it
once and keeps going), when segments are still arriving, and while it backs off after a failure.
A segment acknowledged after assembly puts the track back to `assembly-pending`
(`segments.acknowledge`), and the next pass rebuilds it.

Each claim gets a token (`assembly_claim`); only the worker holding it records its result. A
segment acknowledged during a build clears the token, so that build queues the track again
instead of recording a file without the segment, and a second build never starts alongside it.
Each build uploads under its own file names, so a worker whose claim was taken over can never
overwrite a newer file. Numbers the file doesn't hold are published as `recording.gap` events of
kind `missing` or `corrupt`, once, when the track is assembled.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.db.session import Database
from hirevion_core.ids import uuid7
from hirevion_core.interview_session import realtime
from hirevion_core.models import Interview, Recording, RecordingSegment
from hirevion_core.outbox import publish_event
from hirevion_core.recordings import tracks
from hirevion_core.recordings.continuity import gap_payload
from hirevion_core.recordings.ffmpeg import Concatenator
from hirevion_core.recordings.segments import (
    ENDED_STATUSES,
    GAP_TOPIC,
    acknowledged_through,
    blob_path,
)
from hirevion_core.recordings.settings import RecordingSettings
from hirevion_core.recordings.timeline import SegmentInfo, build_timeline
from hirevion_core.storage.paths import BlobPath, interview_blob
from hirevion_core.storage.service import BlobChanged, BlobTooLarge

log = logging.getLogger(__name__)

BATCH = 50
BACKOFF_SECONDS = 30
MAX_BACKOFF_SECONDS = 600
MISSING_FFMPEG_RETRY = timedelta(minutes=10)
STALE_ASSEMBLY = timedelta(minutes=30)
_CHUNK = 1024 * 1024


class AssemblyStore(Protocol):
    async def download_to(
        self, path: BlobPath, destination: Path, max_bytes: int | None = None
    ) -> None: ...
    async def upload_file(self, path: BlobPath, source: Path, content_type: str) -> None: ...
    async def put(self, path: BlobPath, data: bytes, content_type: str) -> None: ...


@dataclass(frozen=True, slots=True)
class _Part:
    """An acknowledged segment, as the assembly needs it."""

    seq: int
    started_at: datetime
    duration_ms: int
    container: str
    sha256: str
    size: int
    path: BlobPath


@dataclass(slots=True)
class _Work:
    recording_id: UUID
    track: str
    parts: list[_Part]
    claim: UUID
    last_seq: int | None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


async def _sha256(path: Path) -> str:
    """Hashes a (possibly multi-gigabyte) file off the event loop."""
    return await asyncio.to_thread(_sha256_file, path)


def _clock(now: datetime | None) -> datetime:
    """The time to record: the caller's fixed time (tests), else the current time, so a long
    batch never stamps a result or a backoff with the time it started."""
    return now or datetime.now(UTC)


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class Assembler:
    def __init__(
        self,
        db: Database,
        store: AssemblyStore,
        ffmpeg: Concatenator,
        settings: RecordingSettings,
        redis: Redis | None = None,
    ) -> None:
        self.db = db
        self.store = store
        self.ffmpeg = ffmpeg
        self.settings = settings
        self.redis = redis
        self._warned_missing = False

    async def run_due(self, now: datetime | None = None) -> int:
        """Assembles what is due across organisations; returns how many tracks were built."""
        async with self.db.unscoped() as session:
            rows = (
                await session.execute(
                    text("SELECT * FROM recording_due_assembly(:now, :limit, :ended)"),
                    {"now": _clock(now), "limit": BATCH, "ended": list(ENDED_STATUSES)},
                )
            ).all()
        built = 0
        for row in rows:
            try:
                built += await self.assemble_interview(row.organization_id, row.interview_id, now)
            except Exception:
                log.exception("Assembling the recordings of interview %s failed", row.interview_id)
        return built

    async def assemble_interview(
        self, organization_id: UUID, interview_id: UUID, now: datetime | None = None
    ) -> int:
        """Builds every track of an ended interview that is ready; returns how many it built.
        Idempotent: a track that is assembled, or isn't ready, is left alone."""
        if not self.ffmpeg.available():
            await self._wait_for_ffmpeg(organization_id, interview_id, _clock(now))
            return 0
        claimed = await self._claim(organization_id, interview_id, _clock(now))
        built = 0
        for work in claimed:
            try:
                built += await self._assemble(organization_id, interview_id, work, now)
            except Exception as error:
                log.warning(
                    "Assembling %s of interview %s failed: %s", work.track, interview_id, error
                )
                await self._failed(organization_id, work, error, _clock(now))
        return built

    async def _wait_for_ffmpeg(
        self, organization_id: UUID, interview_id: UUID, now: datetime
    ) -> None:
        if not self._warned_missing:
            log.warning(
                "ffmpeg isn't installed (HV_FFMPEG_PATH=%r): recordings stay assembly-pending",
                getattr(self.ffmpeg, "path", None),
            )
            self._warned_missing = True
        async with self.db.tenant(organization_id) as session:
            interview = await session.get(Interview, interview_id)
            if interview is None or interview.status not in ENDED_STATUSES:
                return
            for recording in await _recordings(
                session, interview_id, ("recording", "assembly-pending")
            ):
                recording.status = "assembly-pending"
                recording.ready_at = recording.ready_at or now
                recording.note = "ffmpeg-missing"
                recording.next_attempt_at = now + MISSING_FFMPEG_RETRY

    async def _claim(self, organization_id: UUID, interview_id: UUID, now: datetime) -> list[_Work]:
        """Takes the tracks that are ready: moves them to `assembling` and reads their
        acknowledged segments. A track still waiting for in-flight segments stays pending."""
        settle = now - timedelta(seconds=self.settings.recording_settle_seconds)
        work: list[_Work] = []
        async with self.db.tenant(organization_id) as session:
            interview = await session.get(Interview, interview_id)
            if interview is None or interview.status not in ENDED_STATUSES:
                return []
            for recording in await _recordings(
                session,
                interview_id,
                ("recording", "assembly-pending", "assembling"),
                skip_locked=True,
            ):
                if recording.next_attempt_at is not None and recording.next_attempt_at > now:
                    continue
                # A worker that died mid-assembly leaves `assembling` behind: take it over
                # once it has been quiet for longer than ffmpeg is allowed to run.
                if recording.status == "assembling" and recording.updated_at > now - STALE_ASSEMBLY:
                    continue
                rows = (
                    await session.scalars(
                        select(RecordingSegment)
                        .where(
                            RecordingSegment.interview_id == interview_id,
                            RecordingSegment.track == recording.track,
                        )
                        .order_by(RecordingSegment.seq)
                    )
                ).all()
                if any(r.state != "acknowledged" and r.requested_at > settle for r in rows):
                    recording.status = "assembly-pending"
                    recording.ready_at = recording.ready_at or now
                    recording.note = "waiting-for-uploads"
                    continue
                parts = [
                    _Part(
                        r.seq,
                        r.started_at,
                        r.duration_ms,
                        r.container,
                        r.sha256,
                        r.bytes,
                        blob_path(r),
                    )
                    for r in rows
                    if r.state == "acknowledged"
                ]
                claim = uuid7()
                recording.status = "assembling"
                recording.assembly_claim = claim
                recording.ready_at = recording.ready_at or now
                recording.note = None
                work.append(_Work(recording.id, recording.track, parts, claim, recording.last_seq))
        return work

    async def _assemble(
        self, organization_id: UUID, interview_id: UUID, work: _Work, now: datetime | None
    ) -> int:
        """Builds one track; returns 1 if it recorded an assembled file, else 0."""
        containers = {p.container for p in work.parts}
        if not work.parts:
            await self._finish_empty(organization_id, work, "no acknowledged segments", now)
            return 0
        if len(containers) != 1:
            await self._finish_empty(organization_id, work, "mixed containers in one track", now)
            return 0
        (container,) = containers
        corrupt: set[int] = set()
        included: list[_Part] = []
        with tempfile.TemporaryDirectory(prefix="hv-assemble-") as scratch:
            workdir = Path(scratch)
            names: list[str] = []
            for index, part in enumerate(work.parts):
                name = f"seg-{index:06d}.{container}"
                # Re-check what was acknowledged: the upload URL could write the blob again,
                # with other bytes, or with far more of them, and a blob can go missing. Each is
                # a gap in the file, never a reason to fail the whole track.
                try:
                    await self.store.download_to(part.path, workdir / name, max_bytes=part.size)
                    changed = await _sha256(workdir / name) != part.sha256
                except (BlobTooLarge, BlobChanged, FileNotFoundError):
                    changed = True
                if changed:
                    (workdir / name).unlink(missing_ok=True)
                    corrupt.add(part.seq)
                    continue
                names.append(name)
                included.append(part)
            if not included:
                await self._finish_empty(
                    organization_id, work, "every segment failed its hash", now
                )
                return 0
            output = f"assembled.{container}"
            await self.ffmpeg.concat(workdir, names, output, container)
            produced = workdir / output
            size, digest = produced.stat().st_size, await _sha256(produced)
            timeline = build_timeline(
                work.track,
                container,
                [SegmentInfo(p.seq, p.started_at, p.duration_ms) for p in included],
                corrupt,
                work.last_seq,
            )
            build = work.claim.hex[-12:]
            file_path = interview_blob(
                organization_id,
                interview_id,
                tracks.folder(work.track),
                tracks.assembled_filename(work.track, container, build),
            )
            timeline_path = interview_blob(
                organization_id,
                interview_id,
                tracks.folder(work.track),
                tracks.timeline_filename(work.track, build),
            )
            await self.store.upload_file(
                file_path, produced, tracks.content_type(work.track, container)
            )
            await self.store.put(
                timeline_path,
                json.dumps(timeline, separators=(",", ":")).encode("utf-8"),
                "application/json",
            )
        finished = _clock(now)
        async with self.db.tenant(organization_id) as session:
            recording = await session.get_one(Recording, work.recording_id, with_for_update=True)
            if recording.status != "assembling":
                return 0
            if recording.assembly_claim is None:
                # A segment was acknowledged while this ran: build the track again, with it.
                _requeue(recording, finished)
                return 0
            if recording.assembly_claim != work.claim:
                return 0  # another worker took the claim over; its result is the one recorded
            recording.status = "assembled"
            recording.assembly_claim = None
            recording.container = container
            recording.blob_path = str(file_path)
            recording.timeline_path = str(timeline_path)
            recording.assembled_bytes = size
            recording.assembled_sha256 = digest
            recording.duration_ms = timeline["duration_ms"]
            recording.gaps = timeline["gaps"]
            recording.assembled_at = finished
            recording.attempts = 0
            recording.next_attempt_at = None
            recording.note = None
            for gap in timeline["gaps"]:
                await publish_event(
                    session,
                    organization_id,
                    GAP_TOPIC,
                    gap_payload(
                        interview_id,
                        work.track,
                        kind=gap["reason"],
                        state="closed",
                        from_seq=gap["from_seq"],
                        to_seq=gap["to_seq"],
                        from_time=_parse(gap["from_time"]),
                        to_time=_parse(gap["to_time"]),
                    ),
                    key=str(interview_id),
                )
            through = await acknowledged_through(session, interview_id, work.track)
            last_seq = recording.last_seq
        await self._notify(interview_id, work.track, "assembled", last_seq, through)
        return 1

    async def _finish_empty(
        self, organization_id: UUID, work: _Work, note: str, now: datetime | None
    ) -> None:
        """A track with nothing to join cannot be assembled; say why (a late segment retries)."""
        async with self.db.tenant(organization_id) as session:
            recording = await session.get_one(Recording, work.recording_id, with_for_update=True)
            if recording.status != "assembling":
                return
            if recording.assembly_claim is None:
                _requeue(recording, _clock(now))
            elif recording.assembly_claim == work.claim:
                recording.status = "failed"
                recording.assembly_claim = None
                recording.note = note

    async def _failed(
        self, organization_id: UUID, work: _Work, error: Exception, now: datetime
    ) -> None:
        async with self.db.tenant(organization_id) as session:
            recording = await session.get_one(Recording, work.recording_id, with_for_update=True)
            if recording.status != "assembling":
                return
            if recording.assembly_claim is None:
                _requeue(recording, now)  # a late segment arrived: rebuild, don't back off
                return
            if recording.assembly_claim != work.claim:
                return  # another worker owns the track now
            recording.assembly_claim = None
            recording.attempts += 1
            recording.note = f"{type(error).__name__}: {error}"[:300]
            if recording.attempts >= self.settings.recording_assembly_attempts:
                recording.status = "failed"
            else:
                recording.status = "assembly-pending"
                delay = min(BACKOFF_SECONDS * 2**recording.attempts, MAX_BACKOFF_SECONDS)
                recording.next_attempt_at = now + timedelta(seconds=delay)

    async def _notify(
        self, interview_id: UUID, track: str, status: str, last_seq: int | None, through: int | None
    ) -> None:
        if self.redis is None:
            return
        data: dict[str, Any] = {
            "track": track,
            "status": status,
            "last_seq": last_seq,
            "acknowledged_through": through,
        }
        try:
            await realtime.publish(self.redis, interview_id, "RECORDING_STATUS", data)
        except Exception:
            log.warning("Publishing RECORDING_STATUS failed", exc_info=True)


def _requeue(recording: Recording, now: datetime) -> None:
    """Queues a track again because a segment was acknowledged while it was being built."""
    recording.status = "assembly-pending"
    recording.ready_at = now
    recording.next_attempt_at = None
    recording.note = "late-segment"


async def _recordings(
    session: AsyncSession,
    interview_id: UUID,
    statuses: tuple[str, ...],
    *,
    skip_locked: bool = False,
) -> list[Recording]:
    statement = (
        select(Recording)
        .where(
            Recording.interview_id == interview_id,
            Recording.status.in_(statuses),
            # Egress writes whole files (SP-13); only the desktop's segments are assembled.
            Recording.source == "desktop",
        )
        .order_by(Recording.track)
        .with_for_update(skip_locked=skip_locked)
    )
    found = list((await session.scalars(statement)).all())
    return sorted(found, key=lambda r: tracks.track_order(r.track))
