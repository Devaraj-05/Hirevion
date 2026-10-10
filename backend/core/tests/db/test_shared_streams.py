"""A stream read by two consumer groups (`interview.completed`: the transcripts and the media
worker) must reach both: neither may delete a message the other hasn't read, and each remembers
what it handled under its own key."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from redis.asyncio import Redis

from hirevion_core.documents.consumer import StreamConsumer
from hirevion_core.ids import uuid7
from hirevion_core.outbox import stream_name

pytestmark = pytest.mark.db

ORG = UUID(int=7)


async def publish(redis: Redis, topic: str) -> str:
    event_id = str(uuid7())
    fields: dict[Any, Any] = {
        "id": event_id,
        "org": str(ORG),
        "topic": topic,
        "key": "",
        "payload": json.dumps({"n": 1}),
        "created_at": "2026-10-12T05:00:00+00:00",
    }
    await redis.xadd(stream_name(topic), fields)
    return event_id


def consumer(
    redis: Redis, topic: str, group: str, seen: list[str], **kwargs: Any
) -> StreamConsumer:
    async def handler(organization_id: UUID, payload: dict[str, Any]) -> None:
        seen.append(group)

    return StreamConsumer(redis, handler, topic=topic, group=group, **kwargs)


async def test_two_groups_on_one_topic_each_handle_every_message(valkey: Redis) -> None:
    topic = f"shared-{uuid4().hex[:8]}"
    seen: list[str] = []
    first = consumer(valkey, topic, "transcripts", seen, delete_handled=False)
    second = consumer(valkey, topic, "media", seen, delete_handled=False)
    await first.run_once()  # creates its group
    await second.run_once()
    await publish(valkey, topic)
    assert await first.run_once() == 1  # handled and acknowledged before the other has read it
    assert await second.run_once() == 1
    assert sorted(seen) == ["media", "transcripts"]
    assert await valkey.xlen(stream_name(topic)) == 1  # left for the relay's maxlen to trim


async def test_a_consumer_that_deletes_what_it_handled_starves_the_other_group(
    valkey: Redis,
) -> None:
    topic = f"deleting-{uuid4().hex[:8]}"
    seen: list[str] = []
    first = consumer(valkey, topic, "a", seen)  # the default: delete once handled
    second = consumer(valkey, topic, "b", seen)
    await first.run_once()
    await second.run_once()
    await publish(valkey, topic)
    assert await first.run_once() == 1
    assert await second.run_once() == 0  # why the shared streams don't use it
    assert await valkey.xlen(stream_name(topic)) == 0


async def test_groups_remember_what_they_handled_under_their_own_keys(valkey: Redis) -> None:
    topic = f"keys-{uuid4().hex[:8]}"
    seen: list[str] = []
    first = consumer(valkey, topic, "transcripts", seen, delete_handled=False)
    second = consumer(valkey, topic, "media", seen, delete_handled=False)
    await first.run_once()
    await second.run_once()
    event_id = await publish(valkey, topic)
    await first.run_once()
    assert await valkey.exists(f"hv:{topic}:transcripts:done:{event_id}")
    assert not await valkey.exists(f"hv:{topic}:media:done:{event_id}")
    await second.run_once()  # not mistaken for something already handled
    assert sorted(seen) == ["media", "transcripts"]


async def test_a_consumer_named_for_its_topic_keeps_the_old_done_key(valkey: Redis) -> None:
    topic = f"plain-{uuid4().hex[:8]}"
    seen: list[str] = []
    only = consumer(valkey, topic, topic, seen)
    await only.run_once()
    event_id = await publish(valkey, topic)
    await only.run_once()
    assert await valkey.exists(f"hv:{topic}:done:{event_id}")
