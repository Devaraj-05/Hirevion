"""LiveKit's webhook (SP-09): the room tells the interview when the candidate leaves (an
interruption, under the resume policy) and when the agent leaves while the interview is still
running (a crash: another agent is dispatched and resumes from the checkpoint). Deliveries are
accepted only with LiveKit's signature over the body."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import Request

from hirevion_api.deps import get_db, get_redis
from hirevion_api.interview_session.routes import conductor, media
from hirevion_api.problems import ProblemError
from hirevion_api.routing import api_router
from hirevion_core.access.errors import AccessError
from hirevion_core.interview_session.media import MediaError, MediaEvent
from hirevion_core.interviews.lifecycle import By
from hirevion_core.proctoring.service import ProctorEngine

log = logging.getLogger(__name__)
router = api_router(tags=["interview-session"])
BODY_MAX = 64 * 1024


@router.post("/livekit/webhook", status_code=204)
async def livekit_webhook(request: Request) -> None:
    """Room events from LiveKit, signed with the server's API secret."""
    control = media(request)
    if control is None:
        raise ProblemError(503, "media-unavailable", "No media server is configured")
    body = await request.body()
    if len(body) > BODY_MAX:
        raise ProblemError(413, "webhook-too-large", "Request too large")
    try:
        event = control.parse_webhook(
            body.decode("utf-8", "replace"), request.headers.get("authorization", "")
        )
    except MediaError as error:
        raise ProblemError(401, "webhook-invalid", "Request refused") from error
    if event.interview_id is None or event.organization_id is None:
        return
    runner = conductor(request)
    try:
        # Deliveries can be late or out of order: a candidate who is back isn't interrupted.
        if (
            event.kind == "candidate_left"
            and event.identity is not None
            and await control.candidate_present(event.interview_id, event.identity)
        ):
            return
        if event.kind in ("candidate_left", "room_finished"):
            await runner.interrupt(
                event.organization_id,
                event.interview_id,
                reason=event.kind,
                by=By("system", "livekit"),
                observed_at=event.at,
            )
        elif event.kind == "agent_left":
            await runner.redispatch(event.organization_id, event.interview_id)
        await _proctoring(request, event)
    except AccessError as error:
        # An interview that isn't there or can't change now: nothing to do, and LiveKit needn't
        # retry.
        log.info("LiveKit's %s for interview %s ignored: %s", event.kind, event.interview_id, error)


TRACK_CHANNELS = {"camera": "camera", "microphone": "mic", "screen_share": "screen"}


async def _proctoring(request: Request, event: MediaEvent) -> None:
    """What the room shows about the candidate's devices is the proctoring engine's ground truth
    (SP-14): a track that goes away, the third eye leaving, or the candidate coming and going.
    Deliveries are idempotent: the engine keeps the newest view of each channel."""
    if event.interview_id is None or event.organization_id is None:
        return
    engine = ProctorEngine(get_db(request), get_redis(request))
    channel = TRACK_CHANNELS.get(event.track or "")
    if event.kind in ("track_published", "track_unpublished") and channel is not None:
        state: Literal["up", "down"] = "up" if event.kind == "track_published" else "down"
        await engine.observe(
            event.organization_id,
            event.interview_id,
            channel,
            "livekit",
            state,
            event.at,
        )
    elif event.kind in ("third_eye_joined", "third_eye_left"):
        state = "up" if event.kind == "third_eye_joined" else "down"
        await engine.observe(
            event.organization_id, event.interview_id, "third_eye", "livekit", state, event.at
        )
    elif event.kind in ("candidate_left", "candidate_joined", "room_finished"):
        await engine.wake(event.organization_id, event.interview_id)
