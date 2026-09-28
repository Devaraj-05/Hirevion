import asyncio

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
