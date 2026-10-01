"""The mail stream's consumer: render, send, acknowledge (SP-02 spec, "Email").

Delivery is at least once. A failed send stays pending and is claimed again after
`retry_idle_ms`; after `max_deliveries` attempts the message moves to a dead-letter stream. The
outbox may publish an event twice, so a sent event's id is remembered for a week and a repeat
is dropped. Sent entries are deleted from the stream, so their links don't wait there.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
from collections.abc import Mapping
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from hirevion_core.mail.render import render
from hirevion_core.mail.sender import MAIL_TOPIC, MailSender
from hirevion_core.outbox import stream_name

log = logging.getLogger(__name__)

MAIL_STREAM = stream_name(MAIL_TOPIC)
DEAD_LETTER_STREAM = "hv:dead:mail"
_SENT_PREFIX = "hv:mail:sent:"
_SENT_TTL_SECONDS = 7 * 86_400
_BATCH = 20


def _text(value: Any) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


class MailConsumer:
    def __init__(
        self,
        redis: Redis,
        sender: MailSender,
        *,
        group: str = "mail",
        consumer: str | None = None,
        retry_idle_ms: int = 60_000,
        max_deliveries: int = 5,
    ) -> None:
        self._redis = redis
        self._sender = sender
        self._group = group
        self._consumer = consumer or f"{socket.gethostname()}-{os.getpid()}"
        self._retry_idle_ms = retry_idle_ms
        self._max_deliveries = max_deliveries
        self._group_ready = False

    async def _ensure_group(self) -> None:
        if self._group_ready:
            return
        try:
            # From the start of the stream, so mail queued before the first consumer still goes.
            await self._redis.xgroup_create(MAIL_STREAM, self._group, id="0", mkstream=True)
        except ResponseError as error:
            if "BUSYGROUP" not in str(error):
                raise
        self._group_ready = True

    async def run_once(self, block_ms: int | None = None) -> int:
        """Retries stale pending messages, then reads new ones; returns how many were sent."""
        await self._ensure_group()
        sent = 0
        # redis-py types stream replies loosely; their shape is fixed by the commands.
        claimed: Any = await self._redis.xautoclaim(
            MAIL_STREAM,
            self._group,
            self._consumer,
            min_idle_time=self._retry_idle_ms,
            start_id="0-0",
            count=_BATCH,
        )
        for message_id, fields in claimed[1]:
            sent += await self._handle(_text(message_id), fields)
        fresh: Any = await self._redis.xreadgroup(
            self._group, self._consumer, {MAIL_STREAM: ">"}, count=_BATCH, block=block_ms
        )
        for _stream, messages in fresh or []:
            for message_id, fields in messages:
                sent += await self._handle(_text(message_id), fields)
        return sent

    async def run_forever(self, stop: asyncio.Event, block_ms: int = 1000) -> None:
        while not stop.is_set():
            try:
                await self.run_once(block_ms=block_ms)
            except Exception:
                log.exception("Reading the mail stream failed; retrying in 1s")
                await asyncio.sleep(1)

    async def _handle(self, message_id: str, raw: Mapping[Any, Any]) -> int:
        fields = {_text(key): _text(value) for key, value in raw.items()}
        event_id = fields.get("id", message_id)
        if await self._deliveries(message_id) > self._max_deliveries:
            entry: dict[Any, Any] = dict(fields)
            await self._redis.xadd(DEAD_LETTER_STREAM, entry, maxlen=10_000, approximate=True)
            await self._finish(message_id)
            log.error("Gave up on email %s after %d attempts", event_id, self._max_deliveries)
            return 0
        sent_key = _SENT_PREFIX + event_id
        if await self._redis.exists(sent_key):
            await self._finish(message_id)
            return 0
        try:
            payload = json.loads(fields["payload"])
            mail = render(payload["template"], payload["locale"], payload["context"])
            await self._sender.send(payload["to"], mail)
        except Exception:
            # Never log the payload: it may hold a single-use link.
            log.warning("Sending email %s failed; it will be retried", event_id, exc_info=True)
            return 0
        await self._redis.set(sent_key, "1", ex=_SENT_TTL_SECONDS)
        await self._finish(message_id)
        return 1

    async def _deliveries(self, message_id: str) -> int:
        pending = await self._redis.xpending_range(
            MAIL_STREAM, self._group, min=message_id, max=message_id, count=1
        )
        return int(pending[0]["times_delivered"]) if pending else 1

    async def _finish(self, message_id: str) -> None:
        await self._redis.xack(MAIL_STREAM, self._group, message_id)
        await self._redis.xdel(MAIL_STREAM, message_id)
