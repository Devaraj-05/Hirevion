"""GCRA rate limiting on Valkey (master plan §9: limits per IP, account and organisation)."""

import asyncio

import pytest
from redis.asyncio import Redis

from hirevion_core.ratelimit import RateLimiter, RateRule, reset_limits

pytestmark = pytest.mark.db


async def test_hits_are_allowed_up_to_the_limit(valkey: Redis) -> None:
    limiter, rule = RateLimiter(valkey), RateRule("burst", 3, 60)
    decisions = [await limiter.hit(rule, "203.0.113.9") for _ in range(4)]
    assert [decision.allowed for decision in decisions] == [True, True, True, False]
    assert [decision.remaining for decision in decisions] == [2, 1, 0, 0]
    assert 1 <= decisions[3].retry_after_seconds <= 20
    assert decisions[0].retry_after_seconds == 0


async def test_subjects_are_counted_separately(valkey: Redis) -> None:
    limiter, rule = RateLimiter(valkey), RateRule("single", 1, 60)
    assert (await limiter.hit(rule, "a")).allowed
    assert not (await limiter.hit(rule, "a")).allowed
    assert (await limiter.hit(rule, "b")).allowed


async def test_capacity_returns_over_time(valkey: Redis) -> None:
    limiter, rule = RateLimiter(valkey), RateRule("refill", 2, 1)
    assert [(await limiter.hit(rule, "a")).allowed for _ in range(3)] == [True, True, False]
    await asyncio.sleep(0.6)
    assert (await limiter.hit(rule, "a")).allowed


async def test_concurrent_hits_never_overshoot(valkey: Redis) -> None:
    limiter, rule = RateLimiter(valkey), RateRule("crowd", 10, 60)
    decisions = await asyncio.gather(*(limiter.hit(rule, "a") for _ in range(20)))
    assert sum(decision.allowed for decision in decisions) == 10


@pytest.mark.parametrize(
    ("name", "limit", "period"), [("Bad Name", 1, 1), ("ok", 0, 1), ("ok", 1, 0), ("", 1, 1)]
)
def test_rules_are_checked(name: str, limit: int, period: int) -> None:
    with pytest.raises(ValueError, match="rule"):
        RateRule(name, limit, period)


async def test_resetting_clears_every_limit_and_lockout_but_nothing_else(valkey: Redis) -> None:
    limiter = RateLimiter(valkey)
    rule = RateRule("login-ip", 1, 60)
    assert (await limiter.hit(rule, "203.0.113.7")).allowed
    assert not (await limiter.hit(rule, "203.0.113.7")).allowed
    await valkey.hset("lockout:abc", mapping={"failures": 5})
    await valkey.set("hv:mail:sent:keep", "1")

    assert await reset_limits(valkey) == 2
    assert (await limiter.hit(rule, "203.0.113.7")).allowed
    assert await valkey.exists("lockout:abc") == 0
    assert await valkey.get("hv:mail:sent:keep") == "1"
