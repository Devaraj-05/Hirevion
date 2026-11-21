"""A job runner is ready before its interview arrives (the owner's run of 2026-11-21: the first
runner was made on demand, timed out after 10 s, and the next one loaded the database driver and
the ORM on the event loop while the greeting played, so the voice broke up)."""

import sys
from types import SimpleNamespace
from typing import Any

import pytest
from livekit.agents import AgentServer
from sqlalchemy import inspect

from hirevion_core.models import InterviewSession
from hirevion_interview_agent import warm


def test_warm_up_loads_the_database_driver_and_the_orm() -> None:
    warm.warm_up()
    assert "asyncpg" in sys.modules
    assert inspect(InterviewSession).configured


def test_prewarm_also_loads_the_voice_activity_model(monkeypatch: Any) -> None:
    monkeypatch.setattr(warm.silero.VAD, "load", staticmethod(lambda: "vad"))
    process = SimpleNamespace(userdata={})
    warm.prewarm(process)  # type: ignore[arg-type]
    assert process.userdata["vad"] == "vad"


def test_one_runner_waits_ready_and_a_slow_pc_gets_time_to_make_it() -> None:
    assert warm.IDLE_RUNNERS.dev_default == 1
    # Production keeps LiveKit's own default: one runner per CPU, not a fixed number.
    assert warm.IDLE_RUNNERS.prod_default == AgentServer._default_num_idle_processes.prod_default
    assert warm.INITIALIZE_TIMEOUT_SECONDS >= 60


@pytest.mark.filterwarnings("ignore:`livekit.plugins.turn_detector` is deprecated")
def test_warm_up_loads_what_the_turn_detector_reads_at_the_session_start() -> None:
    # The live check of 2026-11-21: filelock (huggingface_hub's download) loaded on the event
    # loop for 308 ms as the greeting began.
    import livekit.plugins.turn_detector  # noqa: F401  # imported by main() when it is in use

    warm.warm_up()
    assert "huggingface_hub.file_download" in sys.modules
