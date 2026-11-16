"""One agent of a kind per interview: a key in Valkey held while it runs (SP-09c's interviewer
lock, shared with the third eye's vision agent in C7-1)."""

import pytest
from redis.asyncio import Redis

from hirevion_core.interview_session.held_key import HeldKey

pytestmark = pytest.mark.db


async def test_one_holder_at_a_time_and_the_next_takes_over_when_it_lets_go(valkey: Redis) -> None:
    first = HeldKey(valkey, "hv:test:held", owner="job-1", ttl=5)
    second = HeldKey(valkey, "hv:test:held", owner="job-2", ttl=5)
    assert await first.acquire(wait=0)
    assert not await second.acquire(wait=0.3, poll=0.1)
    await first.release()
    assert await second.acquire(wait=0)
    assert await valkey.get("hv:test:held") == "job-2"
    await second.release()
    assert await valkey.get("hv:test:held") is None


async def test_releasing_someone_elses_key_leaves_it(valkey: Redis) -> None:
    holder = HeldKey(valkey, "hv:test:mine", owner="job-1", ttl=5)
    other = HeldKey(valkey, "hv:test:mine", owner="job-2", ttl=5)
    assert await holder.acquire(wait=0)
    await other.release()
    assert await valkey.get("hv:test:mine") == "job-1"
    await holder.release()
