"""The media worker (SP-12): the consumer of finished interviews, the assembly sweep and the
continuity monitor, started with the other workers (`mail.runner.run_workers`).

An `interview.completed` or `interview.abandoned` event asks for the interview's tracks to be
assembled straight away; the sweep catches whatever couldn't be built then (segments still
arriving, ffmpeg missing, a failure backing off) and any track of an ended interview whose event
was missed. Both streams are shared with other consumers, so this one leaves messages on the
stream for the relay's `maxlen` to trim.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from functools import partial
from typing import Any
from uuid import UUID

from redis.asyncio import Redis

from hirevion_core.db.session import Database
from hirevion_core.documents.consumer import StreamConsumer
from hirevion_core.interview_session.transcripts import ABANDONED_TOPIC
from hirevion_core.interview_session.transcripts import TOPIC as COMPLETED_TOPIC
from hirevion_core.recordings.assembly import Assembler, AssemblyStore
from hirevion_core.recordings.ffmpeg import Ffmpeg
from hirevion_core.recordings.monitor import ContinuityMonitor
from hirevion_core.recordings.settings import RecordingSettings

log = logging.getLogger(__name__)

MEDIA_GROUP = "media"
ENDED_TOPICS = (COMPLETED_TOPIC, ABANDONED_TOPIC)


async def handle_interview_ended(
    assembler: Assembler, organization_id: UUID, payload: dict[str, Any]
) -> None:
    """The `interview.completed` / `interview.abandoned` handler: build the interview's tracks."""
    await assembler.assemble_interview(organization_id, UUID(str(payload["interview_id"])))


async def _sweep(assembler: Assembler, stop: asyncio.Event, poll: float) -> None:
    while not stop.is_set():
        try:
            await assembler.run_due()
        except Exception:
            log.exception("Sweeping recordings for assembly failed; retrying in %.0fs", poll)
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), poll)


def media_workers(
    db: Database,
    redis: Redis,
    store: AssemblyStore | None,
    settings: RecordingSettings,
    stop: asyncio.Event,
) -> list[Awaitable[None]]:
    """The media worker's coroutines, for `asyncio.gather`. Without blob storage there is
    nothing to assemble, but continuity is still watched."""
    workers: list[Awaitable[None]] = [
        ContinuityMonitor(db, redis, poll=settings.recording_monitor_seconds).run_forever(stop)
    ]
    if store is None:
        log.warning("No blob storage is configured: recordings won't be assembled")
        return workers
    assembler = Assembler(
        db, store, Ffmpeg(settings.ffmpeg_path, settings.ffmpeg_timeout_seconds), settings, redis
    )
    handler: Callable[[UUID, dict[str, Any]], Awaitable[None]] = partial(
        handle_interview_ended, assembler
    )
    for topic in ENDED_TOPICS:
        consumer = StreamConsumer(
            redis, handler, topic=topic, group=MEDIA_GROUP, delete_handled=False
        )
        workers.append(consumer.run_forever(stop))
    workers.append(_sweep(assembler, stop, settings.recording_poll_seconds))
    return workers
