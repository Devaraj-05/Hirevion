"""The `documents` stream's consumer (ADR-0015): the same delivery rules as the mail consumer.

Delivery is at least once. A failed event stays pending and is claimed again after
`retry_idle_ms`; after `max_deliveries` attempts it moves to a dead-letter stream and
`on_give_up` runs (the document is marked failed). The outbox may publish an event twice, so a
handled event's id is remembered for a week and a repeat is dropped.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from hirevion_core.documents.intake import DOCUMENTS_TOPIC
from hirevion_core.outbox import stream_name

log = logging.getLogger(__name__)

DOCUMENTS_STREAM = stream_name(DOCUMENTS_TOPIC)
DEAD_LETTER_STREAM = "hv:dead:documents"
_DONE_PREFIX = "hv:documents:done:"
_DONE_TTL_SECONDS = 7 * 86_400
_BATCH = 10

Handler = Callable[[UUID, dict[str, Any]], Awaitable[None]]


def _text(value: Any) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


class DocumentConsumer:
    def __init__(
        self,
        redis: Redis,
        handler: Handler,
        *,
        on_give_up: Handler | None = None,
        group: str = "documents",
        consumer: str | None = None,
        retry_idle_ms: int = 60_000,
        max_deliveries: int = 5,
    ) -> None:
        self._redis = redis
        self._handler = handler
        self._on_give_up = on_give_up
        self._group = group
        self._consumer = consumer or f"{socket.gethostname()}-{os.getpid()}"
        self._retry_idle_ms = retry_idle_ms
        self._max_deliveries = max_deliveries
        self._group_ready = False

    async def _ensure_group(self) -> None:
        if self._group_ready:
            return
        try:
            await self._redis.xgroup_create(DOCUMENTS_STREAM, self._group, id="0", mkstream=True)
        except ResponseError as error:
            if "BUSYGROUP" not in str(error):
                raise
        self._group_ready = True

    async def run_once(self, block_ms: int | None = None) -> int:
        """Retries stale pending events, then reads new ones; returns how many were handled."""
        await self._ensure_group()
        handled = 0
        claimed: Any = await self._redis.xautoclaim(
            DOCUMENTS_STREAM,
            self._group,
            self._consumer,
            min_idle_time=self._retry_idle_ms,
            start_id="0-0",
            count=_BATCH,
        )
        for message_id, fields in claimed[1]:
            handled += await self._handle(_text(message_id), fields)
        fresh: Any = await self._redis.xreadgroup(
            self._group, self._consumer, {DOCUMENTS_STREAM: ">"}, count=_BATCH, block=block_ms
        )
        for _stream, messages in fresh or []:
            for message_id, fields in messages:
                handled += await self._handle(_text(message_id), fields)
        return handled

    async def run_forever(self, stop: asyncio.Event, block_ms: int = 1000) -> None:
        while not stop.is_set():
            try:
                await self.run_once(block_ms=block_ms)
            except Exception:
                log.exception("Reading the documents stream failed; retrying in 1s")
                await asyncio.sleep(1)

    async def _handle(self, message_id: str, raw: Mapping[Any, Any]) -> int:
        fields = {_text(key): _text(value) for key, value in raw.items()}
        event_id = fields.get("id", message_id)
        organization_id = UUID(fields["org"])
        payload: dict[str, Any] = json.loads(fields["payload"])
        if await self._deliveries(message_id) > self._max_deliveries:
            entry: dict[Any, Any] = dict(fields)
            await self._redis.xadd(DEAD_LETTER_STREAM, entry, maxlen=10_000, approximate=True)
            if self._on_give_up is not None:
                await self._on_give_up(organization_id, payload)
            await self._finish(message_id)
            log.error(
                "Gave up on document event %s after %d attempts", event_id, self._max_deliveries
            )
            return 0
        done_key = _DONE_PREFIX + event_id
        if await self._redis.exists(done_key):
            await self._finish(message_id)
            return 0
        try:
            await self._handler(organization_id, payload)
        except Exception:
            log.warning("Document event %s failed; it will be retried", event_id, exc_info=True)
            return 0
        await self._redis.set(done_key, "1", ex=_DONE_TTL_SECONDS)
        await self._finish(message_id)
        return 1

    async def _deliveries(self, message_id: str) -> int:
        pending = await self._redis.xpending_range(
            DOCUMENTS_STREAM, self._group, min=message_id, max=message_id, count=1
        )
        return int(pending[0]["times_delivered"]) if pending else 1

    async def _finish(self, message_id: str) -> None:
        await self._redis.xack(DOCUMENTS_STREAM, self._group, message_id)
        await self._redis.xdel(DOCUMENTS_STREAM, message_id)
