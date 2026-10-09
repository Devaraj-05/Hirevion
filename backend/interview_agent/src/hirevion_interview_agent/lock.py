"""One agent per interview (SP-09c): the agent holds `hv:iv:{id}:agent` in Valkey with a short
expiry and refreshes it while it runs. A replacement dispatched after a crash waits for the dead
agent's key to lapse (at most `TTL_SECONDS`), so the interview resumes within about ten seconds
and never has two voices."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from uuid import UUID

from redis.asyncio import Redis

from hirevion_core.interview_session.conductor import agent_key

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


class AgentLock:
    def __init__(
        self, redis: Redis, interview_id: UUID, owner: str, *, ttl: int = TTL_SECONDS
    ) -> None:
        self._redis = redis
        self._key = agent_key(interview_id)
        self._owner = owner
        self._ttl = ttl
        self._refresher: asyncio.Task[None] | None = None
        self.lost = asyncio.Event()
        """Set when another agent holds the interview: this one must stop speaking."""

    async def acquire(self, wait: float = TTL_SECONDS + 4, poll: float = 0.25) -> bool:
        """Takes the lock, waiting up to `wait` seconds for a previous holder's to lapse."""
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
                log.warning("Couldn't refresh the agent lock %s; retrying", self._key)
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
