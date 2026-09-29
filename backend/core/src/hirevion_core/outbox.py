"""The transactional outbox and its relay to Valkey Streams (master plan D12).

A service records a domain event with `publish_event()` in the same transaction as the change
it describes, so the event exists exactly when the change commits. `OutboxRelay` then copies
pending events to the stream `hv:events:<topic>` and stamps them published.

Delivery is at least once: after a crash between XADD and the commit, an event is published
again, so consumers de-duplicate on the `id` field. Events from different transactions carry
no ordering guarantee.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.audit import canonical_json
from hirevion_core.db.session import Database
from hirevion_core.ids import uuid7
from hirevion_core.models import OutboxEvent

log = logging.getLogger(__name__)

STREAM_PREFIX = "hv:events:"
_TOPIC = re.compile(r"[a-z][a-z0-9_.-]{1,62}")


def stream_name(topic: str) -> str:
    """The Valkey stream for `topic`: `interview.completed` -> `hv:events:interview.completed`."""
    if not _TOPIC.fullmatch(topic):
        raise ValueError(f"not a valid event topic: {topic!r}")
    return STREAM_PREFIX + topic


async def publish_event(
    session: AsyncSession,
    organization_id: UUID,
    topic: str,
    payload: Mapping[str, Any],
    key: str | None = None,
) -> UUID:
    """Record an event in the caller's transaction; it is published only if that commits."""
    stream_name(topic)
    canonical_json(payload)  # refuse what jsonb and consumers can't read, now rather than later
    event = OutboxEvent(
        id=uuid7(), organization_id=organization_id, topic=topic, key=key, payload=dict(payload)
    )
    session.add(event)
    await session.flush()
    return event.id


def _stream_fields(event: OutboxEvent) -> dict[str, str]:
    return {
        "id": str(event.id),
        "org": str(event.organization_id),
        "topic": event.topic,
        "key": event.key or "",
        "payload": canonical_json(event.payload).decode("utf-8"),
        "created_at": event.created_at.isoformat(),
    }


class OutboxRelay:
    """Publishes pending outbox events; run it with the relay role's `Database`.

    Several relays may run at once: each claims a batch with FOR UPDATE SKIP LOCKED.
    """

    def __init__(self, db: Database, redis: Redis, batch: int = 100, maxlen: int = 100_000) -> None:
        self.db = db
        self.redis = redis
        self.batch = batch
        self.maxlen = maxlen

    async def run_once(self) -> int:
        """Publish up to one batch; returns how many events were published."""
        claimed: list[UUID] = []
        try:
            async with self.db.unscoped() as session:
                events = (
                    await session.scalars(
                        select(OutboxEvent)
                        .where(OutboxEvent.published_at.is_(None))
                        .order_by(OutboxEvent.created_at)
                        .limit(self.batch)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
                claimed = [event.id for event in events]
                if not events:
                    return 0
                await self._publish(events)
                now = datetime.now(UTC)
                for event in events:
                    event.published_at = now
                    event.attempts += 1
                return len(events)
        except RedisError:
            # The claim rolled back, so the events stay pending; count the failed attempt.
            await self._count_failed_attempt(claimed)
            raise

    async def run_forever(self, stop: asyncio.Event, poll: float = 0.5) -> None:
        """Publish until `stop` is set, waiting `poll` seconds whenever the outbox is drained."""
        while not stop.is_set():
            try:
                published = await self.run_once()
            except Exception:
                log.exception("Publishing outbox events failed; retrying in %.1fs", poll)
                published = 0
            if published < self.batch:
                with suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), poll)

    async def _publish(self, events: Sequence[OutboxEvent]) -> None:
        async with self.redis.pipeline(transaction=False) as pipe:
            for event in events:
                pipe.xadd(
                    stream_name(event.topic),
                    _stream_fields(event),  # type: ignore[arg-type]
                    maxlen=self.maxlen,
                    approximate=True,
                )
            await pipe.execute()

    async def _count_failed_attempt(self, claimed: Sequence[UUID]) -> None:
        if not claimed:
            return
        async with self.db.unscoped() as session:
            await session.execute(
                update(OutboxEvent)
                .where(OutboxEvent.id.in_(claimed), OutboxEvent.published_at.is_(None))
                .values(attempts=OutboxEvent.attempts + 1)
            )
