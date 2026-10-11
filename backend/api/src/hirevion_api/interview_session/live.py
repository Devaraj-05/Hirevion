"""`/ws/interviews/{id}` (PRD §91): an interview's live events for the recruiting team.

A browser's websocket carries the session cookie but no CSRF header, so the handshake must come
from an allowed Origin (cross-site websocket hijacking otherwise), and the session must be live
with `interviews.view` and reach the interview (its resource scope; reviewers only theirs). The
socket replays what's on the stream after `?after=` (from the start without it), then follows;
the session is checked again every minute, so a sign-out or a revoked role ends it.

The proctoring events (SP-14) share the stream but go only to readers who also hold
`reports.proctoring.view`. `follow` is the part `/ws/proctoring/{id}` shares.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID

from fastapi import WebSocket, WebSocketDisconnect

from hirevion_api.auth.cookies import SESSION_COOKIE
from hirevion_api.routing import api_router
from hirevion_core.access.errors import AccessError
from hirevion_core.access.scope import resource_scope
from hirevion_core.db.session import Database
from hirevion_core.identity.grants import load_grants
from hirevion_core.identity.sessions import SessionContext, resolve_session
from hirevion_core.interview_session import realtime
from hirevion_core.interviews import assignment

log = logging.getLogger(__name__)
router = api_router(tags=["interview-session"])

POLICY_VIOLATION = 1008
UNAUTHORISED = 4401
FORBIDDEN = 4403
BLOCK_MS = 15_000
RECHECK_SECONDS = 60
_STREAM_ID = r"^(0|\$|\d{1,20}-\d{1,20})$"

Opened = Callable[[SessionContext, frozenset[str]], Awaitable[None]]


async def _allowed(
    websocket: WebSocket, db: Database, interview_id: UUID, needs: tuple[str, ...]
) -> tuple[SessionContext, frozenset[str]] | int:
    """The session and its permissions when it may watch this interview, else the close code."""
    token = websocket.cookies.get(SESSION_COOKIE)
    if not token:
        return UNAUTHORISED
    context = await resolve_session(
        db, token, settings=websocket.app.state.identity, now=datetime.now(UTC)
    )
    if context is None:
        return UNAUTHORISED
    async with db.tenant(context.organization_id) as session:
        grants = await load_grants(session, context.user_id)
        permissions = frozenset(grants.permissions)
        if not all(need in permissions for need in needs):
            return FORBIDDEN
        scope = await resource_scope(session, context.user_id)
        reviewer_only = None if "candidates.view" in permissions else context.user_id
        try:
            await assignment.get_interview(
                session, interview_id, scope, reviewer_only=reviewer_only
            )
        except AccessError:
            return FORBIDDEN
    return context, permissions


async def follow(
    websocket: WebSocket,
    interview_id: UUID,
    after: str,
    needs: tuple[str, ...],
    *,
    opened: Opened | None = None,
) -> None:
    """Serves the interview's stream to a recruiter who holds every permission in `needs`."""
    origins: frozenset[str] = websocket.app.state.allowed_origins
    if websocket.headers.get("origin") not in origins:
        await websocket.close(code=POLICY_VIOLATION)
        return
    db: Database = websocket.app.state.db
    redis = websocket.app.state.redis
    if not re.match(_STREAM_ID, after):
        await websocket.close(code=POLICY_VIOLATION)
        return
    allowed = await _allowed(websocket, db, interview_id, needs)
    if isinstance(allowed, int):
        await websocket.close(code=allowed)
        return
    context, permissions = allowed
    restricted = (
        frozenset() if "reports.proctoring.view" in permissions else realtime.PROCTORING_TYPES
    )
    await websocket.accept()
    if opened is not None:
        await opened(context, permissions)

    # "$" means only new events: pin it to the newest id now, so later reads miss nothing.
    start = await realtime.last_id(redis, interview_id) if after == "$" else after

    async def pump() -> None:
        last, checked = start, asyncio.get_running_loop().time()
        while True:
            events = await realtime.read(redis, interview_id, last, block_ms=BLOCK_MS)
            sent = False
            for event in events:
                last = event.id
                if event.type in restricted:
                    continue
                await websocket.send_json(event.to_json())
                sent = True
            if not sent:
                await websocket.send_json({"type": "ping"})
            now = asyncio.get_running_loop().time()
            if now - checked > RECHECK_SECONDS:
                checked = now
                again = await _allowed(websocket, db, interview_id, needs)
                if isinstance(again, int):
                    await websocket.close(code=again)
                    return

    async def watch() -> None:
        # The client sends nothing; reading only notices that it has gone.
        while (await websocket.receive())["type"] != "websocket.disconnect":
            pass

    tasks = {asyncio.create_task(pump()), asyncio.create_task(watch())}
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if not task.cancelled() and task.exception() is not None:
                error = task.exception()
                if not isinstance(error, WebSocketDisconnect | RuntimeError):
                    log.error(
                        "The live events of interview %s failed", interview_id, exc_info=error
                    )
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@router.websocket("/ws/interviews/{interview_id}")
async def interview_events(websocket: WebSocket, interview_id: UUID, after: str = "0") -> None:
    await follow(websocket, interview_id, after, ("interviews.view",))
