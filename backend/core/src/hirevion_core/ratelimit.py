"""Rate limiting with GCRA (the generic cell rate algorithm) on Valkey (ADR-0010).

Each (rule, subject) pair keeps one key: the "theoretical arrival time" when its bucket would be
empty. A single script updates it atomically using the server clock, so any number of API
processes share one limit and need no clock agreement. A rule allows `limit` requests at once
and then one every `period_seconds / limit` seconds.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from redis.asyncio import Redis

_NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}")

# KEYS[1] = bucket; ARGV = limit, period in seconds, cost. Returns
# {allowed, remaining, retry_after_ms, reset_ms}.
_GCRA = """
local limit, period, cost = tonumber(ARGV[1]), tonumber(ARGV[2]) * 1000, tonumber(ARGV[3])
local clock = redis.call('TIME')
local now = clock[1] * 1000 + clock[2] / 1000
local interval = period / limit
local tat = math.max(tonumber(redis.call('GET', KEYS[1]) or now), now)
local new_tat = tat + interval * cost
if new_tat - period > now then
  return {0, math.floor((period - (tat - now)) / interval), math.ceil(new_tat - period - now),
          math.ceil(tat - now)}
end
redis.call('SET', KEYS[1], tostring(new_tat), 'PX', math.ceil(new_tat - now))
return {1, math.floor((period - (new_tat - now)) / interval), 0, math.ceil(new_tat - now)}
"""


@dataclass(frozen=True, slots=True)
class RateRule:
    """`limit` requests per `period_seconds` for each subject (an IP, a user, an organisation).

    `fail_closed` refuses requests when Valkey can't be reached (use it for login and similar);
    otherwise the limit is skipped and a warning logged.
    """

    name: str
    limit: int
    period_seconds: int
    fail_closed: bool = False

    def __post_init__(self) -> None:
        if not _NAME.fullmatch(self.name):
            raise ValueError(f"rate rule names are short lower-case words, not {self.name!r}")
        if self.limit < 1 or self.period_seconds < 1:
            raise ValueError("a rate rule needs a limit and a period of at least 1")


@dataclass(frozen=True, slots=True)
class RateDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: int
    reset_seconds: int


class RateLimiter:
    def __init__(self, redis: Redis) -> None:
        self._script = redis.register_script(_GCRA)

    async def hit(self, rule: RateRule, subject: str, cost: int = 1) -> RateDecision:
        """Count one request by `subject` against `rule`."""
        allowed, remaining, retry_ms, reset_ms = await self._script(
            keys=[f"hv:rl:{rule.name}:{subject}"], args=[rule.limit, rule.period_seconds, cost]
        )
        return RateDecision(
            allowed=bool(allowed),
            remaining=max(int(remaining), 0),
            retry_after_seconds=math.ceil(int(retry_ms) / 1000),
            reset_seconds=math.ceil(int(reset_ms) / 1000),
        )
