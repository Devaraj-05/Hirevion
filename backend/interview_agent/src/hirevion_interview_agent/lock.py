"""One interviewer per interview (SP-09c): it holds `hv:iv:{id}:agent` in Valkey with a short
expiry and refreshes it while it runs. A replacement dispatched after a crash waits for the dead
agent's key to lapse (at most `TTL_SECONDS`), so the interview resumes within about ten seconds
and never has two voices. The lock itself is core's `HeldKey`, shared with the vision agent."""

from __future__ import annotations

from uuid import UUID

from redis.asyncio import Redis

from hirevion_core.interview_session.conductor import agent_key
from hirevion_core.interview_session.held_key import REFRESH_SECONDS, TTL_SECONDS, HeldKey

__all__ = ["REFRESH_SECONDS", "TTL_SECONDS", "AgentLock"]


class AgentLock(HeldKey):
    def __init__(
        self, redis: Redis, interview_id: UUID, owner: str, *, ttl: int = TTL_SECONDS
    ) -> None:
        super().__init__(redis, agent_key(interview_id), owner, ttl=ttl)
