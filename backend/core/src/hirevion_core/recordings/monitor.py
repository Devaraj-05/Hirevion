"""The continuity monitor (SP-12): every few seconds it looks at the tracks of the interviews in
progress and, for one that has been silent for longer than its policy allows, records the stall
on its `recordings` row, queues a `recording.gap` outbox event and publishes `RECORDING_STATUS`
to the interview's realtime stream. Each stall is reported once; the next segment of the track
closes it (`segments.request_upload`).

Turning a gap into `SCREEN_CAPTURE_STOPPED` or `TELEMETRY_GAP` is the proctoring engine's job
(SP-14); this only says that the stream stopped reaching the server.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import text

from hirevion_core.db.session import Database
from hirevion_core.interview_session import realtime
from hirevion_core.models import Interview
from hirevion_core.outbox import publish_event
from hirevion_core.recordings.continuity import (
    Stall,
    TrackState,
    find_stalls,
    gap_payload,
)
from hirevion_core.recordings.segments import GAP_TOPIC, acknowledged_through, lock_recording

log = logging.getLogger(__name__)

BATCH = 5000


class _Live:
    """One interview in progress, as the listing function reports it."""

    def __init__(self, row: Any) -> None:
        self.organization_id: UUID = row.organization_id
        self.interview_id: UUID = row.interview_id
        self.started_at: datetime = row.started_at
        self.connected_at: datetime | None = row.connected_at
        self.policy: dict[str, Any] = row.policy or {}
        self.states: dict[str, TrackState] = {}

    def add(self, row: Any) -> None:
        if row.track is not None:
            self.states[row.track] = TrackState(
                row.track, row.last_seq, row.last_ended_at, row.last_segment_at, row.stalled
            )


class ContinuityMonitor:
    def __init__(self, db: Database, redis: Redis, *, poll: float = 10.0) -> None:
        self.db = db
        self.redis = redis
        self.poll = poll

    async def run_once(self, now: datetime | None = None) -> int:
        """Reports the stalls found now; returns how many tracks it newly flagged."""
        moment = now or datetime.now(UTC)
        async with self.db.unscoped() as session:
            rows = (
                await session.execute(
                    text("SELECT * FROM recording_live_tracks(:now, :limit)"),
                    {"now": moment, "limit": BATCH},
                )
            ).all()
        live: dict[UUID, _Live] = {}
        for row in rows:
            live.setdefault(row.interview_id, _Live(row)).add(row)
        flagged = 0
        for item in live.values():
            stalls = find_stalls(
                item.policy,
                item.states,
                started_at=item.started_at,
                connected_at=item.connected_at,
                now=moment,
            )
            if not stalls:
                continue
            try:
                flagged += await self._report(item, [s.track for s in stalls], moment)
            except Exception:
                log.exception("Recording continuity for interview %s failed", item.interview_id)
        return flagged

    async def _report(self, item: _Live, tracks: list[str], now: datetime) -> int:
        """Records the stalls in the interview's own transaction, under the recording rows'
        locks, and re-checks each there: a segment may have arrived since the listing."""
        notices: list[dict[str, Any]] = []
        async with self.db.tenant(item.organization_id) as session:
            interview = await session.get(Interview, item.interview_id)
            if interview is None or interview.status != "in_progress":
                return 0
            for track in tracks:
                recording = await lock_recording(session, interview, track)
                state = TrackState(
                    track,
                    recording.last_seq,
                    recording.last_ended_at,
                    recording.last_segment_at,
                    recording.stalled_since is not None,
                )
                found = [
                    s
                    for s in find_stalls(
                        item.policy,
                        {track: state},
                        started_at=item.started_at,
                        connected_at=item.connected_at,
                        now=now,
                    )
                    if s.track == track
                ]
                if not found:
                    continue
                stall = found[0]
                recording.stalled_since = now
                await publish_event(
                    session,
                    item.organization_id,
                    GAP_TOPIC,
                    _open_payload(item.interview_id, stall, now),
                    key=str(item.interview_id),
                )
                notices.append(
                    {
                        "track": track,
                        "status": "stalled",
                        "last_seq": recording.last_seq,
                        "acknowledged_through": await acknowledged_through(
                            session, item.interview_id, track
                        ),
                    }
                )
        for data in notices:
            try:
                await realtime.publish(self.redis, item.interview_id, "RECORDING_STATUS", data)
            except Exception:
                log.warning("Publishing RECORDING_STATUS failed", exc_info=True)
        return len(notices)

    async def run_forever(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.run_once()
            except Exception:
                log.exception("Checking recording continuity failed; retrying in %.0fs", self.poll)
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), self.poll)


def _open_payload(interview_id: UUID, stall: Stall, now: datetime) -> dict[str, Any]:
    return gap_payload(
        interview_id,
        stall.track,
        kind="stalled",
        state="open",
        from_seq=stall.from_seq,
        to_seq=None,
        from_time=stall.from_time,
        to_time=None,
        detected_at=now,
        silent_seconds=stall.silent_seconds,
        allowed_seconds=stall.allowed_seconds,
    )


__all__ = ["ContinuityMonitor"]
