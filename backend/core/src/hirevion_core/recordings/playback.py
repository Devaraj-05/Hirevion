"""What a reviewer can play back for an interview (SP-12; PRD §97 "recording viewed"): per track
the assembled file and its timeline map once the media worker has built them, and until then each
acknowledged segment. Every URL is read-only and short-lived."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.models import Recording, RecordingSegment
from hirevion_core.recordings import tracks
from hirevion_core.recordings.segments import blob_path
from hirevion_core.storage.paths import BlobPath
from hirevion_core.storage.service import DOWNLOAD_TTL


class DownloadSigner(Protocol):
    def download_url(
        self,
        organization_id: UUID,
        path: BlobPath,
        expires: timedelta = ...,
        filename: str | None = None,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class PlayableFile:
    url: str
    container: str
    bytes: int
    sha256: str
    duration_ms: int


@dataclass(frozen=True, slots=True)
class PlayableSegment:
    seq: int
    started_at: datetime
    duration_ms: int
    url: str


@dataclass(slots=True)
class PlayableTrack:
    track: str
    status: str
    stalled: bool
    first_seq: int | None
    last_seq: int | None
    gaps: list[dict[str, Any]]
    file: PlayableFile | None = None
    timeline_url: str | None = None
    segments: list[PlayableSegment] = field(default_factory=list)


async def playable_tracks(
    session: AsyncSession, signer: DownloadSigner, organization_id: UUID, interview_id: UUID
) -> list[PlayableTrack]:
    rows = (
        await session.scalars(select(Recording).where(Recording.interview_id == interview_id))
    ).all()
    result: list[PlayableTrack] = []
    for recording in sorted(rows, key=lambda r: tracks.track_order(r.track)):
        item = PlayableTrack(
            track=recording.track,
            status=recording.status,
            stalled=recording.stalled_since is not None,
            first_seq=recording.first_seq,
            last_seq=recording.last_seq,
            gaps=list(recording.gaps),
        )
        if (
            recording.status == "assembled"
            and recording.blob_path
            and recording.timeline_path
            and recording.container
        ):
            item.file = PlayableFile(
                url=signer.download_url(
                    organization_id, _blob(organization_id, recording.blob_path)
                ),
                container=recording.container,
                bytes=recording.assembled_bytes or 0,
                sha256=recording.assembled_sha256 or "",
                duration_ms=recording.duration_ms or 0,
            )
            item.timeline_url = signer.download_url(
                organization_id, _blob(organization_id, recording.timeline_path)
            )
        else:
            segments = (
                await session.scalars(
                    select(RecordingSegment)
                    .where(
                        RecordingSegment.interview_id == interview_id,
                        RecordingSegment.track == recording.track,
                        RecordingSegment.state == "acknowledged",
                    )
                    .order_by(RecordingSegment.seq)
                )
            ).all()
            item.segments = [
                PlayableSegment(
                    s.seq,
                    s.started_at,
                    s.duration_ms,
                    signer.download_url(organization_id, blob_path(s)),
                )
                for s in segments
            ]
        result.append(item)
    return result


def _blob(organization_id: UUID, stored: str) -> BlobPath:
    return BlobPath(organization_id, stored.split("/", 1)[1])


def url_lifetime() -> timedelta:
    """How long the URLs in a listing work (the storage service's download lifetime)."""
    return DOWNLOAD_TTL
