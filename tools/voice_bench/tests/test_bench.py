import asyncio
import time

import pytest

from hirevion_voice_bench.bench import AgentEar


def test_wait_until_quiet_gives_up_when_the_agent_never_speaks() -> None:
    ear = AgentEar()
    with pytest.raises(TimeoutError, match="agent never spoke"):
        asyncio.run(ear.wait_until_quiet(first_audio_timeout=0.05))


def test_wait_until_quiet_returns_once_the_agent_has_spoken_and_stopped() -> None:
    async def scenario() -> None:
        ear = AgentEar()
        ear.heard_anything.set()
        ear.last_voiced = 0.0  # long ago
        await ear.wait_until_quiet(first_audio_timeout=0.05)

    asyncio.run(scenario())


def test_waiting_for_a_reply_stops_when_the_agent_leaves() -> None:
    """The interview ended (the agent left the room): no reply is coming, so don't wait out the
    timeout, and say so instead of reporting a slow turn."""

    async def scenario() -> None:
        ear = AgentEar()
        ear.watch_after(0.0)
        asyncio.get_running_loop().call_later(0.05, ear.left.set)
        started = time.perf_counter()
        assert await ear.wait_for_reply(timeout=5) is None
        assert time.perf_counter() - started < 1

    asyncio.run(scenario())
