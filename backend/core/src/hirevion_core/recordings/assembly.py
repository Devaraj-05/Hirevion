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
"""

from __future__ import annotations

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
from hirevion_core.interview_session import realtime
from hirevion_core.models import Interview, Recording, RecordingSegment
from hirevion_core.recordings import tracks
from hirevion_core.recordings.ffmpeg import Concatenator
from hirevion_core.recordings.segments import ENDED_STATUSES, acknowledged_through, blob_path
from hirevion_core.recordings.settings import RecordingSettings
from hirevion_core.recordings.timeline import SegmentInfo, build_timeline
from hirevion_core.storage.paths import BlobPath, interview_blob

log = logging.getLogger(__name__)

BATCH = 50
BACKOFF_SECONDS = 30
MAX_BACKOFF_SECONDS = 600
MISSING_FFMPEG_RETRY = timedelta(minutes=10)
_CHUNK = 1024 * 1024


class AssemblyStore(Protocol):
    async def download_to(self, path: BlobPath, destination: Path) -> None: ...
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
    path: BlobPath


@dataclass(slots=True)
class _Work:
    recording_id: UUID
    track: str
    parts: list[_Part]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


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
        moment = now or datetime.now(UTC)
        async with self.db.unscoped() as session:
            rows = (
                await session.execute(
                    text("SELECT * FROM recording_due_assembly(:now, :limit)"),
                    {"now": moment, "limit": BATCH},
                )
            ).all()
        built = 0
        for row in rows:
            try:
                built += await self.assemble_interview(
                    row.organization_id, row.interview_id, moment
                )
            except Exception:
                log.exception("Assembling the recordings of interview %s failed", row.interview_id)
        return built

    async def assemble_interview(
        self, organization_id: UUID, interview_id: UUID, now: datetime | None = None
    ) -> int:
        """Builds every track of an ended interview that is ready; returns how many it built.
        Idempotent: a track that is assembled, or isn't ready, is left alone."""
        moment = now or datetime.now(UTC)
        if not self.ffmpeg.available():
            await self._wait_for_ffmpeg(organization_id, interview_id, moment)
            return 0
        claimed = await self._claim(organization_id, interview_id, moment)
        built = 0
        for work in claimed:
            try:
                await self._assemble(organization_id, interview_id, work, moment)
                built += 1
            except Exception as error:
                log.warning(
                    "Assembling %s of interview %s failed: %s", work.track, interview_id, error
                )
                await self._failed(organization_id, work.recording_id, error, moment)
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
                session, interview_id, ("recording", "assembly-pending"), skip_locked=True
            ):
                if recording.next_attempt_at is not None and recording.next_attempt_at > now:
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
                    _Part(r.seq, r.started_at, r.duration_ms, r.container, r.sha256, blob_path(r))
                    for r in rows
                    if r.state == "acknowledged"
                ]
                recording.status = "assembling"
                recording.ready_at = recording.ready_at or now
                recording.note = None
                work.append(_Work(recording.id, recording.track, parts))
        return work

    async def _assemble(
        self, organization_id: UUID, interview_id: UUID, work: _Work, now: datetime
    ) -> None:
        containers = {p.container for p in work.parts}
        if not work.parts:
            await self._finish_empty(organization_id, work, "no acknowledged segments")
            return
        if len(containers) != 1:
            await self._finish_empty(organization_id, work, "mixed containers in one track")
            return
        (container,) = containers
        corrupt: set[int] = set()
        included: list[_Part] = []
        with tempfile.TemporaryDirectory(prefix="hv-assemble-") as scratch:
            workdir = Path(scratch)
            names: list[str] = []
            for index, part in enumerate(work.parts):
                name = f"seg-{index:06d}.{container}"
                await self.store.download_to(part.path, workdir / name)
                # Re-check what was acknowledged: the upload URL could write the blob again.
                if _sha256_file(workdir / name) != part.sha256:
                    (workdir / name).unlink()
                    corrupt.add(part.seq)
                    continue
                names.append(name)
                included.append(part)
            if not included:
                await self._finish_empty(organization_id, work, "every segment failed its hash")
                return
            output = f"assembled.{container}"
            await self.ffmpeg.concat(workdir, names, output, container)
            produced = workdir / output
            size, digest = produced.stat().st_size, _sha256_file(produced)
            timeline = build_timeline(
                work.track,
                container,
                [SegmentInfo(p.seq, p.started_at, p.duration_ms) for p in included],
                corrupt,
            )
            file_path = interview_blob(
                organization_id,
                interview_id,
                tracks.folder(work.track),
                tracks.assembled_filename(work.track, container),
            )
            timeline_path = interview_blob(
                organization_id,
                interview_id,
                tracks.folder(work.track),
                tracks.timeline_filename(work.track),
            )
            await self.store.upload_file(
                file_path, produced, tracks.content_type(work.track, container)
            )
            await self.store.put(
                timeline_path,
                json.dumps(timeline, separators=(",", ":")).encode("utf-8"),
                "application/json",
            )
        status: str | None = None
        async with self.db.tenant(organization_id) as session:
            recording = await session.get_one(Recording, work.recording_id, with_for_update=True)
            # A segment acknowledged while this ran put the track back to `assembly-pending`;
            # keep that, and the next pass builds the file again.
            if recording.status == "assembling":
                recording.status = "assembled"
                recording.container = container
                recording.blob_path = str(file_path)
                recording.timeline_path = str(timeline_path)
                recording.assembled_bytes = size
                recording.assembled_sha256 = digest
                recording.duration_ms = timeline["duration_ms"]
                recording.gaps = timeline["gaps"]
                recording.assembled_at = now
                recording.attempts = 0
                recording.next_attempt_at = None
                recording.note = None
                status = "assembled"
            through = await acknowledged_through(session, interview_id, work.track)
            last_seq = recording.last_seq
        if status is not None:
            await self._notify(interview_id, work.track, status, last_seq, through)

    async def _finish_empty(self, organization_id: UUID, work: _Work, note: str) -> None:
        """A track with nothing to join cannot be assembled; say why (a late segment retries)."""
        async with self.db.tenant(organization_id) as session:
            recording = await session.get_one(Recording, work.recording_id, with_for_update=True)
            if recording.status == "assembling":
                recording.status = "failed"
                recording.note = note

    async def _failed(
        self, organization_id: UUID, recording_id: UUID, error: Exception, now: datetime
    ) -> None:
        async with self.db.tenant(organization_id) as session:
            recording = await session.get_one(Recording, recording_id, with_for_update=True)
            if recording.status != "assembling":
                return
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


async def _recordings(
    session: AsyncSession,
    interview_id: UUID,
    statuses: tuple[str, ...],
    *,
    skip_locked: bool = False,
) -> list[Recording]:
    statement = (
        select(Recording)
        .where(Recording.interview_id == interview_id, Recording.status.in_(statuses))
        .order_by(Recording.track)
        .with_for_update(skip_locked=skip_locked)
    )
    found = list((await session.scalars(statement)).all())
    return sorted(found, key=lambda r: tracks.track_order(r.track))
