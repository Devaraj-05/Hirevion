"""The `documents` stream's consumer (ADR-0015): the same delivery rules as the mail consumer.

Delivery is at least once. A failed event stays pending and is claimed again after
`retry_idle_ms`; after `max_deliveries` attempts it moves to a dead-letter stream and
`on_give_up` runs (the document is marked failed). The outbox may publish an event twice, so an
event's id is claimed before its handler runs and remembered for a week once it is handled: a
repeat, even one read by another consumer while the first is still working, is dropped. An entry
that can't be read at all is set aside in the dead-letter stream, so it never stalls the rest.
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
_DONE_TTL_SECONDS = 7 * 86_400
# A claim on an event ends before a lost consumer's message is claimed again (`retry_idle_ms`), so
# a crash never makes an event look handled.
_CLAIM_SHARE = 0.9
# Reading a document can take minutes (up to 50 scanned pages, one paid OCR call each), and one
# AI call with its retries can take longer than the default minute. The consumers of such work
# (documents, screening, evaluation) wait this long before they take an event from a consumer that
# went quiet: at the default minute, a slow one was started a second time while the first was
# working, and its claim (90% of this) had run out.
SLOW_RETRY_IDLE_MS = 10 * 60_000
_BATCH = 10

Handler = Callable[[UUID, dict[str, Any]], Awaitable[None]]


def _text(value: Any) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


class StreamConsumer:
    """Consumes one outbox topic's stream (`documents`, `screening`, ...).

    A stream read by several consumer groups (`interview.completed` has the transcripts and the
    media worker) must be consumed with `delete_handled=False`, so one group finishing a message
    doesn't take it from the others; the relay's `maxlen` trims the stream instead."""

    def __init__(
        self,
        redis: Redis,
        handler: Handler,
        *,
        topic: str = DOCUMENTS_TOPIC,
        on_give_up: Handler | None = None,
        group: str | None = None,
        consumer: str | None = None,
        retry_idle_ms: int = 60_000,
        max_deliveries: int = 5,
        delete_handled: bool = True,
    ) -> None:
        self._topic = topic
        self._stream = stream_name(topic)
        self._dead_letter = f"hv:dead:{topic}"
        group = group or topic
        # Groups that share a topic each remember what they handled.
        self._done_prefix = f"hv:{topic}:done:" if group == topic else f"hv:{topic}:{group}:done:"
        self._delete_handled = delete_handled
        self._redis = redis
        self._handler = handler
        self._on_give_up = on_give_up
        self._group = group
        self._consumer = consumer or f"{socket.gethostname()}-{os.getpid()}"
        self._retry_idle_ms = retry_idle_ms
        self._claim_seconds = max(1, int(retry_idle_ms / 1000 * _CLAIM_SHARE))
        self._max_deliveries = max_deliveries
        self._group_ready = False

    async def _ensure_group(self) -> None:
        if self._group_ready:
            return
        try:
            await self._redis.xgroup_create(self._stream, self._group, id="0", mkstream=True)
        except ResponseError as error:
            if "BUSYGROUP" not in str(error):
                raise
        self._group_ready = True

    async def run_once(self, block_ms: int | None = None) -> int:
        """Retries stale pending events, then reads new ones; returns how many were handled."""
        await self._ensure_group()
        handled = 0
        try:
            claimed: Any = await self._redis.xautoclaim(
                self._stream,
                self._group,
                self._consumer,
                min_idle_time=self._retry_idle_ms,
                start_id="0-0",
                count=_BATCH,
            )
            for message_id, fields in claimed[1]:
                handled += await self._handle(_text(message_id), fields)
            fresh: Any = await self._redis.xreadgroup(
                self._group, self._consumer, {self._stream: ">"}, count=_BATCH, block=block_ms
            )
            for _stream, messages in fresh or []:
                for message_id, fields in messages:
                    handled += await self._handle(_text(message_id), fields)
        except ResponseError as error:
            if "NOGROUP" in str(error):  # the stream was lost (a restart without persistence)
                self._group_ready = False  # the next pass creates the group again
            raise
        return handled

    async def run_forever(self, stop: asyncio.Event, block_ms: int = 1000) -> None:
        while not stop.is_set():
            try:
                await self.run_once(block_ms=block_ms)
            except Exception:
                log.exception("Reading the %s stream failed; retrying in 1s", self._topic)
                await asyncio.sleep(1)

    async def _handle(self, message_id: str, raw: Mapping[Any, Any]) -> int:
        fields = {_text(key): _text(value) for key, value in raw.items()}
        event_id = fields.get("id", message_id)
        try:
            organization_id = UUID(fields["org"])
            payload: dict[str, Any] = json.loads(fields["payload"])
            if not isinstance(payload, dict):
                raise TypeError("the payload is not an object")
        except (KeyError, ValueError, TypeError):
            log.error("Set aside an unreadable %s entry %s", self._topic, event_id)
            unreadable: dict[Any, Any] = dict(fields) or {"raw": ""}
            await self._redis.xadd(self._dead_letter, unreadable, maxlen=10_000, approximate=True)
            await self._finish(message_id)
            return 0
        if await self._deliveries(message_id) > self._max_deliveries:
            if self._on_give_up is not None:
                try:
                    await self._on_give_up(organization_id, payload)
                except Exception:
                    # Left pending, so the hook runs again; nothing is dead-lettered twice.
                    log.warning(
                        "The give-up step for %s event %s failed",
                        self._topic,
                        event_id,
                        exc_info=True,
                    )
                    return 0
            entry: dict[Any, Any] = dict(fields)
            await self._redis.xadd(self._dead_letter, entry, maxlen=10_000, approximate=True)
            await self._finish(message_id)
            log.error(
                "Gave up on %s event %s after %d attempts",
                self._topic,
                event_id,
                self._max_deliveries,
            )
            return 0
        done_key = self._done_prefix + event_id
        if not await self._redis.set(done_key, "claimed", nx=True, ex=self._claim_seconds):
            # Handled already, or being handled right now by another consumer: either way this
            # copy has nothing left to do. (A consumer that dies mid-way leaves a claim that
            # expires before its message is claimed again, so the event is not lost.)
            await self._finish(message_id)
            return 0
        try:
            await self._handler(organization_id, payload)
        except Exception:
            log.warning(
                "%s event %s failed; it will be retried", self._topic, event_id, exc_info=True
            )
            await self._redis.delete(done_key)
            return 0
        await self._redis.set(done_key, "1", ex=_DONE_TTL_SECONDS)
        await self._finish(message_id)
        return 1

    async def _deliveries(self, message_id: str) -> int:
        pending = await self._redis.xpending_range(
            self._stream, self._group, min=message_id, max=message_id, count=1
        )
        return int(pending[0]["times_delivered"]) if pending else 1

    async def _finish(self, message_id: str) -> None:
        await self._redis.xack(self._stream, self._group, message_id)
        # Deleting is for streams with a single group: another group may not have read it yet.
        if self._delete_handled:
            await self._redis.xdel(self._stream, message_id)


# The documents consumer is the first user of the class, and keeps its name.
DocumentConsumer = StreamConsumer
