"""One agent of a kind per interview (SP-09c, C7-1): the agent holds a key in Valkey with a short
expiry and refreshes it while it runs. A replacement dispatched after a crash waits for the dead
agent's key to lapse (at most the expiry), so the work resumes in seconds and never runs twice.
The interviewer holds `hv:iv:{id}:agent`; the third eye's vision agent `hv:iv:{id}:vision`."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from redis.asyncio import Redis

log = logging.getLogger(__name__)

TTL_SECONDS = 8
REFRESH_SECONDS = 3.0
_RELEASE = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) "
    "else return 0 end"
)
_REFRESH = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end"
)


class HeldKey:
    def __init__(self, redis: Redis, key: str, owner: str, *, ttl: int = TTL_SECONDS) -> None:
        self._redis = redis
        self._key = key
        self._owner = owner
        self._ttl = ttl
        self._refresher: asyncio.Task[None] | None = None
        self.lost = asyncio.Event()
        """Set when another agent holds the key: this one must stop."""

    async def acquire(self, wait: float = TTL_SECONDS + 4, poll: float = 0.25) -> bool:
        """Takes the key, waiting up to `wait` seconds for a previous holder's to lapse."""
        deadline = asyncio.get_running_loop().time() + wait
        while not await self._redis.set(self._key, self._owner, nx=True, ex=self._ttl):
            if asyncio.get_running_loop().time() >= deadline:
                return False
            await asyncio.sleep(poll)
        self._refresher = asyncio.create_task(self._refresh())
        return True

    async def _refresh(self) -> None:
        while True:
            await asyncio.sleep(REFRESH_SECONDS)
            try:
                kept = await self._redis.eval(_REFRESH, 1, self._key, self._owner, self._ttl)
                if not kept:
                    # It lapsed (the loop stalled past the TTL): take it back if it's free.
                    kept = await self._redis.set(self._key, self._owner, nx=True, ex=self._ttl)
            except Exception:
                log.warning("Couldn't refresh %s; retrying", self._key)
                continue
            if not kept:
                log.warning("Another agent holds %s; this one stops", self._key)
                self.lost.set()
                return

    async def release(self) -> None:
        if self._refresher is not None:
            self._refresher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._refresher
        await self._redis.eval(_RELEASE, 1, self._key, self._owner)
