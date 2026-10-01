"""Progressive lockout after failed sign-ins (SP-02 spec, "Sign-in, sessions and CSRF").

After `threshold` failures an account waits `base` seconds, and each further failure doubles the
wait up to `maximum`. A success resets it. Keys hold a SHA-256 of the email, never the email.
"""

from __future__ import annotations

import hashlib
import math
import time
from collections.abc import Callable

from redis.asyncio import Redis

from hirevion_core.identity.settings import IdentitySettings

_DAY = 86_400


class Lockout:
    def __init__(
        self,
        redis: Redis,
        *,
        settings: IdentitySettings | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        resolved = settings or IdentitySettings()
        self._redis = redis
        self._threshold = resolved.lockout_threshold
        self._base = resolved.lockout_base_seconds
        self._maximum = resolved.lockout_max_seconds
        self._clock = clock

    @staticmethod
    def _key(email: str) -> str:
        digest = hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()
        return f"lockout:{digest}"

    async def retry_after(self, email: str) -> int | None:
        """Seconds until the account may try again, or None if it isn't locked."""
        until = await self._redis.hget(self._key(email), "until")
        if until is None:
            return None
        remaining = float(until) - self._clock()
        return math.ceil(remaining) if remaining > 0 else None

    async def record_failure(self, email: str) -> int | None:
        """Counts a failure; returns the new wait in seconds once the account is locked."""
        key = self._key(email)
        failures = int(await self._redis.hincrby(key, "failures", 1))
        await self._redis.expire(key, self._maximum + _DAY)
        if failures < self._threshold:
            return None
        # Past the cap more doublings change nothing, so the shift stays small.
        doublings = min(failures - self._threshold, 32)
        wait = min(self._base << doublings, self._maximum)
        await self._redis.hset(key, "until", str(self._clock() + wait))
        return wait

    async def reset(self, email: str) -> None:
        await self._redis.delete(self._key(email))
