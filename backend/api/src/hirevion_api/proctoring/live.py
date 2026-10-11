"""`/ws/proctoring/{id}` (PRD §65, §91): the live dashboard's events.

The interview's stream (`hv:rt:interview:{id}`) as `/ws/interviews/{id}` serves it, for readers
who hold both `reports.proctoring.view` and `interviews.view` (the stream carries what was
said). `?after=` replays from the last event id seen, so a dashboard that reconnects receives
the alerts it missed; the proctoring snapshot (`GET /proctoring/{id}/live`) covers anything older
than the stream keeps. Opening the dashboard is audited, once every five minutes per person.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import WebSocket

from hirevion_api.interview_session.live import follow
from hirevion_api.routing import api_router
from hirevion_core.access import audit
from hirevion_core.access.actor import Actor
from hirevion_core.identity.sessions import SessionContext

log = logging.getLogger(__name__)
router = api_router(tags=["proctoring"])

AUDIT_QUIET = 300
NEEDS = ("reports.proctoring.view", "interviews.view")


@router.websocket("/ws/proctoring/{interview_id}")
async def proctoring_events(websocket: WebSocket, interview_id: UUID, after: str = "0") -> None:
    async def opened(context: SessionContext, permissions: frozenset[str]) -> None:
        key = f"hv:pc:audit:proctoring.live_viewed:{context.user_id}:{interview_id}"
        try:
            if not await websocket.app.state.redis.set(key, "1", nx=True, ex=AUDIT_QUIET):
                return
            actor = Actor(
                context.user_id,
                context.organization_id,
                permissions,
                ip=websocket.client.host if websocket.client else None,
                user_agent=websocket.headers.get("user-agent"),
            )
            async with websocket.app.state.db.tenant(context.organization_id) as session:
                await audit.record(
                    session,
                    actor,
                    "proctoring.live_viewed",
                    "interview",
                    interview_id,
                    details={"via": "websocket"},
                )
        except Exception:
            log.exception("Couldn't audit the live view of interview %s", interview_id)

    await follow(websocket, interview_id, after, NEEDS, opened=opened)
