"""The desktop's proctoring routes, as `docs/api/contracts/proctoring.md` writes them (SP-14).
Every call carries the interview-session token with a fresh DPoP proof; the interview is the
token's own, and a proctor session of another interview is never found."""

from __future__ import annotations

from uuid import UUID

from fastapi import Request, Response

from hirevion_api.candidate_auth.deps import AnyInterviewSession
from hirevion_api.deps import get_db, get_redis
from hirevion_api.problems import ProblemError
from hirevion_api.proctoring.schemas import (
    EventsAck,
    EventsBody,
    EvidenceUploadBody,
    EvidenceUploadResponse,
    HeartbeatAck,
    HeartbeatBody,
    ProctorSessionResponse,
    SessionBody,
    SnapshotRequest,
)
from hirevion_api.ratelimit import enforce
from hirevion_api.routing import api_router
from hirevion_core.proctoring.evidence import Uploads
from hirevion_core.proctoring.normaliser import Incoming
from hirevion_core.proctoring.service import ProctorEngine
from hirevion_core.ratelimit import RateRule

router = api_router(tags=["proctoring"])

SESSIONS = RateRule("pc-session", 30, 60)
EVENTS = RateRule("pc-events", 240, 60)
HEARTBEATS = RateRule("pc-heartbeat", 120, 60)
EVIDENCE = RateRule("pc-evidence", 120, 60)


def engine(request: Request) -> ProctorEngine:
    return ProctorEngine(get_db(request), get_redis(request))


@router.post("/proctoring/session")
async def open_proctor_session(
    body: SessionBody, request: Request, response: Response, principal: AnyInterviewSession
) -> ProctorSessionResponse:
    """Opens the interview's proctor session, or returns the one already open, with the policy it
    is pinned to."""
    if body.interview_id != principal.claims.interview_id:
        raise ProblemError(403, "wrong-interview", "This token is for another interview")
    await enforce(request, response, SESSIONS, str(body.interview_id))
    opened = await engine(request).open_session(
        principal.organization_id, body.interview_id, body.app_version
    )
    return ProctorSessionResponse.model_validate(opened.view())


def _interview(principal: AnyInterviewSession) -> UUID:
    interview_id = principal.claims.interview_id
    if interview_id is None:  # AnyInterviewSession refuses these; this keeps the type honest
        raise ProblemError(403, "wrong-interview", "This token is for no interview")
    return interview_id


@router.post("/proctoring/events")
async def send_proctor_events(
    body: EventsBody, request: Request, response: Response, principal: AnyInterviewSession
) -> EventsAck:
    """A batch of events, sequenced by the device. Stored once per `seq`; the answer says how
    far everything has arrived and which numbers are still missing."""
    await enforce(request, response, EVENTS, str(body.proctor_session_id))
    interview_id = _interview(principal)
    items = [
        Incoming(
            seq=event.seq,
            event=event.event,
            source=event.source,
            started_at=event.started_at,
            duration_ms=event.duration_ms,
            confidence=event.confidence,
            evidence=[ref.model_dump() for ref in event.evidence],
            details=event.details,
        )
        for event in body.events
    ]
    ack = await engine(request).ingest(
        principal.organization_id, interview_id, body.proctor_session_id, items
    )
    return EventsAck(acked_through=ack.acked_through, missing=ack.missing)


@router.post("/proctoring/heartbeat")
async def send_proctor_heartbeat(
    body: HeartbeatBody, request: Request, response: Response, principal: AnyInterviewSession
) -> HeartbeatAck:
    """The device's state every few seconds. The server keeps its own view too: missing
    heartbeats are a gap in telemetry, whatever the device says."""
    await enforce(request, response, HEARTBEATS, str(body.proctor_session_id))
    ack = await engine(request).heartbeat(
        principal.organization_id,
        _interview(principal),
        body.proctor_session_id,
        body.model_dump(exclude={"proctor_session_id"}),
    )
    return HeartbeatAck(
        server_time=ack.server_time,
        missing=ack.missing,
        snapshot_requests=[
            SnapshotRequest(
                request_id=r.request_id,
                event_id=r.event_id,
                kind=r.kind,  # type: ignore[arg-type]
                requested_at=r.requested_at,
            )
            for r in ack.snapshots
        ],
    )


@router.post("/proctoring/evidence-uploads")
async def request_evidence_upload(
    body: EvidenceUploadBody, request: Request, response: Response, principal: AnyInterviewSession
) -> EvidenceUploadResponse:
    """A write-only URL (five minutes) for one snapshot; the event then names its `blob_path`."""
    await enforce(request, response, EVIDENCE, str(body.proctor_session_id))
    storage = getattr(request.app.state, "storage", None)
    if storage is None or getattr(storage, "upload_url", None) is None:
        raise ProblemError(503, "storage-unavailable", "File storage unavailable")
    slot = await engine(request).evidence_upload(
        principal.organization_id,
        _interview(principal),
        body.proctor_session_id,
        _uploads(storage),
        kind=body.kind,
        seq=body.seq,
        request_id=body.request_id,
        content_type=body.content_type,
        size=body.bytes,
        sha256=body.sha256,
    )
    return EvidenceUploadResponse(
        upload_url=slot.upload_url, blob_path=slot.blob_path, headers=slot.headers
    )


def _uploads(storage: object) -> Uploads:
    return storage  # type: ignore[return-value]  # checked above: it has `upload_url`
