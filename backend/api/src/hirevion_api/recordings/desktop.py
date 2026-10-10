"""The desktop's recording routes, as `docs/api/contracts/recordings.md` writes them (SP-12).
Every call carries the interview-session token with a fresh DPoP proof (ADR-0021); none takes a
recruiter's cookie. The token names one interview, and every route compares it with the
interview the request is about."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from fastapi import Depends, Request, Response

from hirevion_api.candidate_auth.deps import (
    AnyInterviewSession,
    CandidatePrincipal,
    InterviewSession,
)
from hirevion_api.deps import get_db, get_redis, get_storage
from hirevion_api.problems import ProblemError
from hirevion_api.ratelimit import enforce, rate_limited
from hirevion_api.recordings.schemas import (
    AckBody,
    AckResponse,
    RecoveryResponse,
    SegmentBody,
    TrackProgress,
    UploadResponse,
)
from hirevion_api.routing import api_router
from hirevion_core.interview_session import realtime
from hirevion_core.models import Interview
from hirevion_core.ratelimit import RateRule
from hirevion_core.recordings import segments
from hirevion_core.recordings.segments import Refused, SegmentDeclaration, SegmentStore

log = logging.getLogger(__name__)

router = api_router(tags=["recordings"])

# Four tracks upload a segment every 10 s, and a desktop catching up after a network loss asks
# for a few hundred at once; the per-interview limit applies once the token is checked.
SEGMENTS_BY_INTERVIEW = RateRule("rec-segment", 600, 60)
ACKS_BY_INTERVIEW = RateRule("rec-ack", 600, 60)
RECORDINGS_BY_IP = RateRule("rec-ip", 3000, 60)


def token_interview(principal: CandidatePrincipal) -> UUID:
    """The interview the session token is for (an interview-scope token always names one)."""
    interview_id = principal.claims.interview_id
    if interview_id is None:
        raise ProblemError(401, "token-invalid", "Sign in to continue")
    return interview_id


def _problem(error: Refused) -> ProblemError:
    return ProblemError(error.status, error.code, error.title, **error.extra)


def _store(request: Request) -> SegmentStore:
    return cast(SegmentStore, get_storage(request))


async def _publish(request: Request, notices: list[segments.StatusNotice]) -> None:
    """The realtime events produced by a committed request; best effort, the outbox events
    already hold the facts."""
    for notice in notices:
        try:
            await realtime.publish(
                get_redis(request), notice.interview_id, "RECORDING_STATUS", notice.data
            )
        except Exception:
            log.warning("Publishing RECORDING_STATUS failed", exc_info=True)


@router.post("/recordings/segments", dependencies=[Depends(rate_limited(RECORDINGS_BY_IP))])
async def request_segment_upload(
    body: SegmentBody, request: Request, response: Response, principal: AnyInterviewSession
) -> UploadResponse:
    """A write-only URL for one segment's blob (15 minutes). Asking again for the same
    `(interview, track, seq)` returns the same `segment_id` with a fresh URL."""
    if body.interview_id != token_interview(principal):
        raise ProblemError(403, "wrong-interview", "This token is for another interview")
    await enforce(request, response, SEGMENTS_BY_INTERVIEW, str(body.interview_id))
    store = _store(request)
    declared = SegmentDeclaration(
        interview_id=body.interview_id,
        track=body.track,
        seq=body.seq,
        started_at=body.started_at,
        duration_ms=body.duration_ms,
        bytes=body.bytes,
        sha256=body.sha256,
        container=body.container,
        codec=body.codec,
    )
    try:
        async with get_db(request).tenant(principal.organization_id) as session:
            interview = await session.get(Interview, body.interview_id)
            if interview is None:
                raise ProblemError(404, "interview-not-found", "No such interview")
            grant, notices = await segments.request_upload(
                session, store, interview, declared, now=datetime.now(UTC)
            )
    except Refused as error:
        raise _problem(error) from error
    await _publish(request, notices)
    return UploadResponse(
        segment_id=grant.segment_id,
        upload_url=grant.upload_url,
        expires_at=grant.expires_at,
        headers=grant.headers,
    )


@router.post(
    "/recordings/segments/{segment_id}/ack",
    dependencies=[Depends(rate_limited(RECORDINGS_BY_IP))],
)
async def acknowledge_segment(
    segment_id: UUID,
    body: AckBody,
    request: Request,
    response: Response,
    principal: AnyInterviewSession,
) -> AckResponse:
    """Reads the blob and checks its size and SHA-256 against the declaration. Only now may the
    desktop delete its local copy."""
    interview_id = token_interview(principal)
    await enforce(request, response, ACKS_BY_INTERVIEW, str(interview_id))
    try:
        await segments.acknowledge(
            get_db(request),
            _store(request),
            principal.organization_id,
            interview_id,
            segment_id,
            body.sha256,
            now=datetime.now(UTC),
        )
    except Refused as error:
        raise _problem(error) from error
    return AckResponse(status="acknowledged")


@router.get(
    "/recordings/interviews/{interview_id}/segments",
    dependencies=[Depends(rate_limited(RECORDINGS_BY_IP))],
)
async def recovery_listing(
    interview_id: UUID, request: Request, principal: InterviewSession
) -> RecoveryResponse:
    """What the server holds, per track, for the desktop's next launch after a crash."""
    async with get_db(request).tenant(principal.organization_id) as session:
        interview = await session.get(Interview, interview_id)
        if interview is None:
            raise ProblemError(404, "interview-not-found", "No such interview")
        progress = await segments.recovery(session, interview)
    return RecoveryResponse(
        tracks={
            track: TrackProgress(
                acknowledged_through=item.acknowledged_through, missing=item.missing
            )
            for track, item in progress.items()
        }
    )
