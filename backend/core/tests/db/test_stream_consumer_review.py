"""D1 code review of the stream consumer (SP-04a): one bad entry cannot stall a stream, a lost
consumer group comes back, a failing give-up hook is retried, and an event published twice is
handled once even by two consumers at the same time."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from redis.asyncio import Redis

from hirevion_core.documents.consumer import StreamConsumer
from hirevion_core.ids import uuid7
from hirevion_core.outbox import stream_name

pytestmark = pytest.mark.db

ORG = UUID(int=9)


async def publish(redis: Redis, topic: str, fields: dict[Any, Any] | None = None) -> str:
    event_id = str(uuid7())
    entry: dict[Any, Any] = fields or {
        "id": event_id,
        "org": str(ORG),
        "topic": topic,
        "key": "",
        "payload": json.dumps({"n": 1}),
        "created_at": "2026-10-18T05:00:00+00:00",
    }
    await redis.xadd(stream_name(topic), entry)
    return event_id


def consumer(redis: Redis, topic: str, handled: list[int], **kwargs: Any) -> StreamConsumer:
    async def handler(organization_id: UUID, payload: dict[str, Any]) -> None:
        handled.append(payload["n"])

    return StreamConsumer(redis, handler, topic=topic, group=topic, **kwargs)


async def test_a_malformed_entry_is_set_aside_and_the_ones_after_it_are_handled(
    valkey: Redis,
) -> None:
    topic = f"bad-{uuid4().hex[:8]}"
    handled: list[int] = []
    worker = consumer(valkey, topic, handled)
    await worker.run_once()
    await publish(valkey, topic, {"id": "broken", "payload": "not json"})  # no organisation
    await publish(valkey, topic, {"id": "worse", "org": "nope", "payload": "[1"})
    await publish(valkey, topic)
    assert await worker.run_once() == 1
    assert handled == [1]
    assert await valkey.xlen(f"hv:dead:{topic}") == 2
    pending: Any = await valkey.xpending(stream_name(topic), topic)
    assert pending["pending"] == 0


async def test_a_deleted_stream_gets_its_consumer_group_back(valkey: Redis) -> None:
    topic = f"gone-{uuid4().hex[:8]}"
    handled: list[int] = []
    worker = consumer(valkey, topic, handled)
    await worker.run_once()
    await valkey.delete(stream_name(topic))
    await publish(valkey, topic)  # the stream is back, without its group
    with pytest.raises(Exception, match="NOGROUP"):
        await worker.run_once()
    assert await worker.run_once() == 1  # the next pass recreates the group
    assert handled == [1]


async def test_a_give_up_hook_that_fails_is_retried_not_repeated_into_the_dead_letters(
    valkey: Redis,
) -> None:
    topic = f"giveup-{uuid4().hex[:8]}"
    calls: list[int] = []

    async def handler(organization_id: UUID, payload: dict[str, Any]) -> None:
        raise RuntimeError("always fails")

    async def give_up(organization_id: UUID, payload: dict[str, Any]) -> None:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("the database is down")

    worker = StreamConsumer(
        valkey,
        handler,
        topic=topic,
        group=topic,
        on_give_up=give_up,
        retry_idle_ms=0,
        max_deliveries=1,
    )
    await worker.run_once()
    await publish(valkey, topic)
    for _ in range(6):  # deliveries 1 and 2 fail the handler; the third gives up
        await worker.run_once()
    assert len(calls) == 2  # the hook failed once and was tried again
    assert await valkey.xlen(f"hv:dead:{topic}") == 1
    assert await valkey.xlen(stream_name(topic)) == 0


async def test_an_event_published_twice_is_handled_once_by_two_consumers_at_once(
    valkey: Redis,
) -> None:
    topic = f"twice-{uuid4().hex[:8]}"
    started: list[int] = []
    release = asyncio.Event()

    async def handler(organization_id: UUID, payload: dict[str, Any]) -> None:
        started.append(1)
        await release.wait()

    first = StreamConsumer(valkey, handler, topic=topic, group=topic, consumer="a")
    second = StreamConsumer(valkey, handler, topic=topic, group=topic, consumer="b")
    await first.run_once()
    fields: dict[Any, Any] = {
        "id": str(uuid7()),
        "org": str(ORG),
        "topic": topic,
        "key": "",
        "payload": json.dumps({"n": 1}),
        "created_at": "2026-10-18T05:00:00+00:00",
    }
    await publish(valkey, topic, fields)
    one = asyncio.create_task(first.run_once())
    await asyncio.sleep(0.3)  # the first consumer holds the event, mid-handler
    await publish(valkey, topic, fields)  # the outbox delivers it a second time
    assert await asyncio.wait_for(second.run_once(), 3) == 0  # dropped, not run alongside
    release.set()
    assert await one == 1
    assert started == [1]
