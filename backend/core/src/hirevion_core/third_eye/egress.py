"""LiveKit Egress (moved from SP-12 to SP-13; PRD §49, §85): the conversation's audio (the
candidate's microphone and the agent's voice, mixed by a room-composite Egress) and each
publication of the third eye's camera (a track Egress, VP8 into WebM, no transcoding).

Each run is a `recordings` row with `source = 'egress'` and a numbered track
(`conversation-audio-N`, `third-eye-N`), planned in §85's folders before Egress starts, so a
webhook that arrives early still finds it. When LiveKit reports the run ended, `egress.ended` is
queued; the media worker then makes the file a blob (through `EgressOutput`), hashes it, writes a
one-span timeline map and marks the row `assembled`, so playback lists it like any track.

`EgressOutput` keeps the cloud out of this module: locally Egress writes into a directory shared
with the worker (a Docker volume) and the worker uploads it; in the cloud Egress writes straight
into the blob container and the worker only reads its size and hash.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import func, select

from hirevion_core.db.session import Database
from hirevion_core.ids import uuid7
from hirevion_core.interview_session import realtime
from hirevion_core.interview_session.media import (
    EgressReport,
    EgressTarget,
    MediaControl,
    MediaError,
)
from hirevion_core.models import Interview, Recording
from hirevion_core.outbox import publish_event
from hirevion_core.recordings import tracks
from hirevion_core.recordings.segments import stored_blob
from hirevion_core.recordings.timeline import SegmentInfo, build_timeline
from hirevion_core.storage.paths import BlobPath, interview_blob, safe_filename
from hirevion_core.third_eye.settings import ThirdEyeSettings

log = logging.getLogger(__name__)

TOPIC = "egress.ended"
AUDIO = "conversation-audio"
THIRD_EYE = "third-eye"
CONTAINERS = {AUDIO: "mp4", THIRD_EYE: "webm"}
CONTENT_TYPES = {AUDIO: "audio/mp4", THIRD_EYE: "video/webm"}
MAX_ATTEMPTS = 5


class EgressFileMissing(Exception):
    """The file Egress reported isn't where it should be (yet)."""


class EgressStore(Protocol):
    async def upload_file_hashed(
        self, path: BlobPath, source: Path, content_type: str
    ) -> tuple[int, str]: ...
    async def put(self, path: BlobPath, data: bytes, content_type: str) -> None: ...
    async def digest(
        self, path: BlobPath, max_bytes: int | None = None
    ) -> tuple[int, str] | None: ...


class EgressOutput(Protocol):
    def target(self, path: BlobPath) -> EgressTarget:
        """Where Egress writes the file that becomes `path`."""
        ...

    async def collect(self, path: BlobPath, content_type: str) -> tuple[int, str]:
        """Makes Egress's file the blob `path`; returns its size and SHA-256."""
        ...

    async def cleanup(self, path: BlobPath) -> None:
        """Forgets Egress's own copy once the blob is registered."""
        ...


@dataclass(frozen=True, slots=True)
class SharedVolumeOutput:
    """Local development: Egress writes under `container_dir`, which is `local_dir` here."""

    local_dir: Path
    container_dir: str
    store: EgressStore

    def _local(self, path: BlobPath) -> Path:
        local = (self.local_dir / str(path)).resolve()
        if not local.is_relative_to(self.local_dir.resolve()):
            raise ValueError("an Egress file outside its directory")
        return local

    def target(self, path: BlobPath) -> EgressTarget:
        return EgressTarget(f"{self.container_dir.rstrip('/')}/{path}")

    async def collect(self, path: BlobPath, content_type: str) -> tuple[int, str]:
        source = self._local(path)
        if not await asyncio.to_thread(source.is_file):
            # Uploaded by an earlier attempt that couldn't record it: the blob is the file.
            found = await self.store.digest(path)
            if found is None:
                raise EgressFileMissing(str(path))
            return found
        return await self.store.upload_file_hashed(path, source, content_type)

    async def cleanup(self, path: BlobPath) -> None:
        await asyncio.to_thread(self._local(path).unlink, missing_ok=True)


@dataclass(frozen=True, slots=True)
class BlobOutput:
    """The cloud: Egress uploads into the container itself (`azure` credentials in its request)."""

    account: str
    key: str
    container: str
    store: EgressStore

    def target(self, path: BlobPath) -> EgressTarget:
        return EgressTarget(str(path), azure=(self.account, self.key, self.container))

    async def collect(self, path: BlobPath, content_type: str) -> tuple[int, str]:
        found = await self.store.digest(path)
        if found is None:
            raise EgressFileMissing(str(path))
        return found

    async def cleanup(self, path: BlobPath) -> None:
        return None


def build_output(settings: ThirdEyeSettings, store: EgressStore | None) -> EgressOutput | None:
    if store is None or settings.egress_output == "off":
        return None
    if settings.egress_output == "azure":
        from hirevion_core.storage.service import load_storage_settings

        storage = load_storage_settings()
        return BlobOutput(
            storage.azure_storage_account,
            storage.azure_storage_key.get_secret_value(),
            storage.azure_storage_container,
            store,
        )
    return SharedVolumeOutput(settings.egress_local_dir, settings.egress_container_dir, store)


def _records(policy: dict[str, Any], kind: str) -> bool:
    recording = policy.get("recording") or {}
    if kind == AUDIO:
        voice = policy.get("answer_mode") != "text"
        return voice and bool(recording.get("audio", True))
    # The third eye is a camera: it is recorded when the interview records its cameras.
    return bool(recording.get("camera", True))


class EgressRecorder:
    """Starts Egress runs from the room's webhooks and registers what they wrote."""

    def __init__(
        self, db: Database, redis: Redis, media: MediaControl, output: EgressOutput
    ) -> None:
        self._db = db
        self._redis = redis
        self._media = media
        self._output = output

    async def _plan(
        self, organization_id: UUID, interview_id: UUID, kind: str, now: datetime
    ) -> tuple[UUID, BlobPath] | None:
        """Adds the run's row, numbered after the interview's earlier runs of `kind`, under the
        interview's lock. None when the policy doesn't record it, the interview isn't open, or
        (for the audio) a run is already recording."""
        async with self._db.tenant(organization_id) as session:
            interview = await session.get(Interview, interview_id, with_for_update=True)
            if interview is None or interview.status not in ("in_progress", "interrupted"):
                return None
            if not _records(interview.policy or {}, kind):
                return None
            existing = (
                await session.execute(
                    select(Recording.status, func.count())
                    .where(
                        Recording.interview_id == interview_id,
                        Recording.source == "egress",
                        Recording.track.like(f"{kind}-%"),
                    )
                    .group_by(Recording.status)
                )
            ).all()
            counts = {status: count for status, count in existing}
            if kind == AUDIO and counts.get("recording"):
                return None
            track = tracks.egress_track(kind, sum(counts.values()) + 1)
            path = interview_blob(
                organization_id,
                interview_id,
                tracks.EGRESS_FOLDERS[kind],
                safe_filename(f"{track}-full.{CONTAINERS[kind]}"),
            )
            row = Recording(
                id=uuid7(),
                organization_id=organization_id,
                interview_id=interview_id,
                track=track,
                source="egress",
                status="recording",
                container=CONTAINERS[kind],
                blob_path=str(path),
                started_at=now,
            )
            session.add(row)
            return row.id, path

    async def _started(
        self, organization_id: UUID, recording_id: UUID, egress_id: str | None, error: str = ""
    ) -> None:
        async with self._db.tenant(organization_id) as session:
            row = await session.get_one(Recording, recording_id, with_for_update=True)
            if egress_id is not None:
                row.egress_id = egress_id
            else:
                row.status, row.note = "failed", error[:200] or "egress-unavailable"

    async def start_audio(self, organization_id: UUID, interview_id: UUID, now: datetime) -> None:
        planned = await self._plan(organization_id, interview_id, AUDIO, now)
        if planned is None:
            return
        recording_id, path = planned
        try:
            egress_id = await self._media.start_audio_egress(
                interview_id, self._output.target(path)
            )
        except MediaError as error:
            log.warning("The conversation audio of %s isn't recorded: %s", interview_id, error)
            await self._started(organization_id, recording_id, None, str(error))
            return
        await self._started(organization_id, recording_id, egress_id)

    async def start_third_eye(
        self, organization_id: UUID, interview_id: UUID, track_sid: str, now: datetime
    ) -> bool:
        """Records the third eye's camera track; False when nothing was started (the interview
        isn't running yet, the policy doesn't record cameras, or Egress refused)."""
        planned = await self._plan(organization_id, interview_id, THIRD_EYE, now)
        if planned is None:
            return False
        recording_id, path = planned
        try:
            egress_id = await self._media.start_track_egress(
                interview_id, track_sid, self._output.target(path)
            )
        except MediaError as error:
            log.warning("The third eye of %s isn't recorded: %s", interview_id, error)
            await self._started(organization_id, recording_id, None, str(error))
            return True  # tried; the failed row says why, and a retry would fail alike
        await self._started(organization_id, recording_id, egress_id)
        return True


async def egress_ended(
    db: Database, organization_id: UUID, interview_id: UUID, report: EgressReport, now: datetime
) -> bool:
    """LiveKit's `egress_ended`: queue the file for collection, or record the failure. The row
    is found by its Egress id, or by its planned file (a run that ended before its id was
    stored). True if a row changed."""
    async with db.tenant(organization_id) as session:
        row = await session.scalar(
            select(Recording)
            .where(
                Recording.interview_id == interview_id,
                Recording.source == "egress",
                (Recording.egress_id == report.egress_id)
                | (Recording.blob_path == report.filename),
            )
            .with_for_update()
        )
        if row is None or row.status != "recording":
            return False
        row.egress_id = row.egress_id or report.egress_id
        if report.started_at is not None:
            row.started_at = report.started_at
        row.duration_ms = report.duration_ms or None
        if report.status != "complete":
            row.status, row.note = "failed", (report.error or "egress-failed")[:200]
            return True
        row.status, row.ready_at = "assembly-pending", now
        await publish_event(
            session,
            organization_id,
            TOPIC,
            {"interview_id": str(interview_id), "recording_id": str(row.id)},
            key=str(interview_id),
        )
        return True


async def collect(
    db: Database,
    redis: Redis | None,
    output: EgressOutput,
    store: EgressStore,
    organization_id: UUID,
    payload: dict[str, Any],
    *,
    now: datetime | None = None,
) -> None:
    """The `egress.ended` handler: Egress's file becomes the blob, with a timeline map."""
    recording_id = UUID(str(payload["recording_id"]))
    async with db.tenant(organization_id) as session:
        row = await session.get(Recording, recording_id)
        if row is None or row.source != "egress" or row.status != "assembly-pending":
            return
        track, stored = row.track, row.blob_path or ""
        started = row.started_at or row.created_at
        duration = row.duration_ms or 0
        attempts = row.attempts
    kind = AUDIO if track.startswith(AUDIO) else THIRD_EYE
    path = stored_blob(organization_id, stored)
    try:
        size, sha = await output.collect(path, CONTENT_TYPES[kind])
    except EgressFileMissing:
        async with db.tenant(organization_id) as session:
            row = await session.get_one(Recording, recording_id, with_for_update=True)
            row.attempts = attempts + 1
            row.note = "egress-file-missing"
            if row.attempts >= MAX_ATTEMPTS:
                row.status = "failed"
                return
        raise
    timeline = build_timeline(
        track, CONTAINERS[kind], [SegmentInfo(0, started, max(duration, 1))], (), 0
    )
    timeline_path = BlobPath(
        organization_id,
        str(path.key).rsplit("/", 1)[0] + "/" + safe_filename(f"{track}-timeline.json"),
    )
    await store.put(
        timeline_path,
        json.dumps(timeline, separators=(",", ":")).encode("utf-8"),
        "application/json",
    )
    finished = now or datetime.now(UTC)
    async with db.tenant(organization_id) as session:
        row = await session.get_one(Recording, recording_id, with_for_update=True)
        if row.status != "assembly-pending":
            return
        row.status = "assembled"
        row.assembled_bytes, row.assembled_sha256 = size, sha
        row.timeline_path = str(timeline_path)
        row.duration_ms = duration or None
        row.assembled_at = finished
        row.note = None
        interview_id = row.interview_id
    # Only now: had the row not been updated, a retry would need the file again.
    await output.cleanup(path)
    if redis is not None:
        try:
            await realtime.publish(
                redis, interview_id, "RECORDING_STATUS", {"track": track, "status": "assembled"}
            )
        except Exception:
            log.warning("Publishing RECORDING_STATUS failed", exc_info=True)
