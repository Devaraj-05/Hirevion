from types import SimpleNamespace
from typing import Any

from hirevion_interview_agent.load import session_load


def server_with(sessions: int) -> Any:
    return SimpleNamespace(active_jobs=[object()] * sessions)


def test_load_is_the_share_of_sessions_in_use() -> None:
    load = session_load(max_sessions=4)
    assert load(server_with(0)) == 0.0
    assert load(server_with(2)) == 0.5


def test_load_is_capped_at_full() -> None:
    assert session_load(max_sessions=4)(server_with(9)) == 1.0
