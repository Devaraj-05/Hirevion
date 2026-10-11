"""The recruiter's playback of an interview's recordings (SP-12; PRD §97 "recording viewed").

It needs `reports.interview.view` and reaches only interviews the caller's resource scope covers
(reviewers: only theirs), like the transcript. Every listing hands out short-lived read-only
URLs, so each one is written to the audit chain."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import Request

from hirevion_api.access.deps import own_tenant
from hirevion_api.authz import Principal, requires
from hirevion_api.deps import get_storage
from hirevion_api.recordings.schemas import (
    GapItem,
    PlaybackFile,
    PlaybackResponse,
    PlaybackSegment,
    PlaybackTrack,
)
from hirevion_api.routing import api_router
from hirevion_core.access.audit import record
from hirevion_core.access.scope import resource_scope
from hirevion_core.interviews import assignment
from hirevion_core.recordings.playback import DownloadSigner, playable_tracks, url_lifetime

router = api_router(tags=["interviews"])

Views = Annotated[Principal, requires("reports.interview.view")]


@router.get("/interviews/{interview_id}/recordings")
async def interview_recordings(
    interview_id: UUID, request: Request, principal: Views
) -> PlaybackResponse:
    """Each track's assembled file and timeline map (read URLs valid for 5 minutes), or, until
    the media worker has built it, each acknowledged segment."""
    signer = cast(DownloadSigner, get_storage(request))
    issued = datetime.now(UTC)  # the URLs expire after this
    async with own_tenant(request, principal) as session:
        scope = await resource_scope(session, principal.user_id)
        interview = await assignment.get_interview(
            session, interview_id, scope, reviewer_only=principal.reviewer_only
        )
        found = await playable_tracks(session, signer, principal.organization_id, interview.id)
        await record(
            session,
            principal.actor(request),
            "recording.viewed",
            "interview",
            interview.id,
            details={
                "tracks": [t.track for t in found],
                "files": sum(1 for t in found if t.file is not None),
                "segments": sum(len(t.segments) for t in found),
            },
        )
    return PlaybackResponse(
        interview_id=interview_id,
        expires_at=issued + url_lifetime(),
        tracks=[
            PlaybackTrack(
                track=t.track,
                status=t.status,  # type: ignore[arg-type]
                stalled=t.stalled,
                first_seq=t.first_seq,
                last_seq=t.last_seq,
                gaps=[GapItem.model_validate(g) for g in t.gaps],
                file=PlaybackFile(
                    url=t.file.url,
                    container=t.file.container,  # type: ignore[arg-type]
                    bytes=t.file.bytes,
                    sha256=t.file.sha256,
                    duration_ms=t.file.duration_ms,
                )
                if t.file is not None
                else None,
                timeline_url=t.timeline_url,
                segments=[
                    PlaybackSegment(
                        seq=s.seq, started_at=s.started_at, duration_ms=s.duration_ms, url=s.url
                    )
                    for s in t.segments
                ],
            )
            for t in found
        ],
    )
