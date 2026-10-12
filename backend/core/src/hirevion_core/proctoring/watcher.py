"""The proctoring workers (SP-14): the watcher that looks at every open proctor session that is
due (a missed heartbeat, a channel the server saw go down, an event still growing), and the
consumer of `recording.gap`, the outbox topic SP-12's upload service raises when a recorded
track has a hole in it (`hirevion_core.recordings.continuity.gap_payload`).

- `kind` `stalled`, `state` `open`: the track went silent; `closed`: it flows again (or its
  late segments arrived). These are votes on the track's channel, so the watcher raises the
  event when the stall lasts and grows its severity: `SCREEN_CAPTURE_STOPPED` for a screen,
  `TELEMETRY_GAP` for the camera and microphone (§64).
- `kind` `missing` or `corrupt` (always closed): a hole found when the track was assembled,
  stored as an event of the hole's length.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from hirevion_core.interview_session.conductor import Conductor
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


async def handle_noted(
    conductor: Conductor, organization_id: UUID, payload: dict[str, Any]
) -> None:
    """A `proctor.noted` event (written with the proctoring event it describes) fills the
    interview's proctor summary and, for a CRITICAL one, the reminder at the next turn. A busy
    turn lock raises `Conflict`, and the consumer tries again."""
    await conductor.note_proctor_event(
        organization_id,
        UUID(str(payload["interview_id"])),
        str(payload["kind"]),
        str(payload["severity"]),
    )


def _time(value: Any) -> datetime | None:
    if not value:
        return None
    moment = datetime.fromisoformat(str(value))
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


async def handle_gap(engine: ProctorEngine, organization_id: UUID, payload: dict[str, Any]) -> None:
    """A `recording.gap` event becomes (or lengthens) the matching proctoring event."""
    interview_id = UUID(str(payload["interview_id"]))
    track = str(payload["track"])
    kind = str(payload["kind"])
    start, end = _time(payload.get("from_time")), _time(payload.get("to_time"))
    if kind == "stalled":
        closed = payload.get("state") == "closed"
        at = (end if closed else start) or _time(payload.get("detected_at")) or datetime.now(UTC)
        await engine.observe_stall(organization_id, interview_id, track, not closed, at)
        return
    if kind in ("missing", "corrupt") and start is not None:
        length = int(((end or start) - start).total_seconds() * 1000)
        await engine.record_gap(
            organization_id,
            interview_id,
            track,
            start,
            length,
            {"kind": kind, "from_seq": payload.get("from_seq"), "to_seq": payload.get("to_seq")},
        )
        return
    log.info("Ignoring recording.gap of kind %r for interview %s", kind, interview_id)
