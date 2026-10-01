"""Progressive lockout after failed sign-ins (SP-02 spec, "Sign-in, sessions and CSRF")."""

import pytest
from redis.asyncio import Redis

from hirevion_core.identity.lockout import Lockout

pytestmark = pytest.mark.db

EMAIL = "Ravi@Acme.example.test"


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


async def test_five_failures_lock_for_a_minute_then_the_wait_doubles(valkey: Redis) -> None:
    clock = Clock()
    lockout = Lockout(valkey, clock=clock)
    for _ in range(4):
        assert await lockout.record_failure(EMAIL) is None
    assert await lockout.retry_after(EMAIL) is None
    assert await lockout.record_failure(EMAIL) == 60
    assert await lockout.retry_after(EMAIL) == 60

    clock.now += 61
    assert await lockout.retry_after(EMAIL) is None
    assert await lockout.record_failure(EMAIL) == 120


async def test_the_wait_is_capped_at_an_hour(valkey: Redis) -> None:
    lockout = Lockout(valkey, clock=Clock())
    waits = [await lockout.record_failure(EMAIL) for _ in range(20)]
    assert waits[-1] == 3600


async def test_the_lock_counts_down(valkey: Redis) -> None:
    clock = Clock()
    lockout = Lockout(valkey, clock=clock)
    for _ in range(5):
        await lockout.record_failure(EMAIL)
    clock.now += 45
    assert await lockout.retry_after(EMAIL) == 15


async def test_success_resets_and_case_does_not_matter(valkey: Redis) -> None:
    lockout = Lockout(valkey, clock=Clock())
    for _ in range(5):
        await lockout.record_failure(EMAIL)
    assert await lockout.retry_after(EMAIL.lower()) == 60
    await lockout.reset(EMAIL.upper())
    assert await lockout.retry_after(EMAIL) is None


async def test_the_key_holds_no_email(valkey: Redis) -> None:
    await Lockout(valkey, clock=Clock()).record_failure(EMAIL)
    keys = [key for key in await valkey.keys("*")]
    assert len(keys) == 1
    assert "acme" not in str(keys[0]).lower()
    assert await valkey.ttl(keys[0]) > 3600
