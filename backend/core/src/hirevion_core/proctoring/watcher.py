"""The proctoring workers (SP-14): the watcher that looks at every open proctor session that is
due (a missed heartbeat, a channel the server saw go down, an event still growing), and the
consumer of `recording.gap`, the outbox topic SP-12's upload service raises when a recording has
a hole in it.

`recording.gap`'s payload: `{"interview_id", "kind", "started_at", "duration_ms"}`, with `kind`
one of `screen`, `camera`, `audio` or `third-eye`. A payload with `from` and `to` (ISO times)
instead of `started_at` and `duration_ms` is read too.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import datetime
from typing import Any
from uuid import UUID

from hirevion_core.proctoring.service import ProctorEngine

log = logging.getLogger(__name__)

GAP_TOPIC = "recording.gap"
BATCH = 200


class ProctorWatcher:
    def __init__(self, engine: ProctorEngine, *, poll: float = 1.0) -> None:
        self._engine = engine
        self._poll = poll

    async def run_once(self) -> int:
        """Looks at every session that is due; returns how many it looked at."""
        due = await self._engine.sessions_due(limit=BATCH)
        for organization_id, session_id in due:
            try:
                await self._engine.tick(organization_id, session_id)
            except Exception:
                log.exception("Watching proctor session %s failed", session_id)
        return len(due)

    async def run_forever(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                looked = await self.run_once()
            except Exception:
                log.exception("Listing the proctor sessions to watch failed")
                looked = 0
            if looked < BATCH:
                with suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), self._poll)


async def handle_gap(engine: ProctorEngine, organization_id: UUID, payload: dict[str, Any]) -> None:
    """A `recording.gap` event becomes (or lengthens) the matching proctoring event."""
    started = payload.get("started_at") or payload.get("from")
    if started is None:
        raise ValueError("a recording gap needs started_at")
    start = datetime.fromisoformat(str(started))
    duration = payload.get("duration_ms")
    if duration is None and payload.get("to") is not None:
        duration = int((datetime.fromisoformat(str(payload["to"])) - start).total_seconds() * 1000)
    kind = str(payload.get("kind") or payload.get("stream") or "")
    await engine.record_gap(
        organization_id,
        UUID(str(payload["interview_id"])),
        kind,
        start,
        int(duration or 0),
        {key: payload[key] for key in ("segment", "reason") if key in payload},
    )
