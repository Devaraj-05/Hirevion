"""Worker load for LiveKit dispatch.

LiveKit's default load is the whole machine's CPU use, so a busy host (or a developer's PC)
makes the worker look full and rooms silently get no agent. Load here is the share of
sessions in use instead, which makes dispatch predictable; SP-09 sizes `max_sessions` from
load tests.
"""

from __future__ import annotations

from collections.abc import Callable, Sized
from typing import Protocol


class _HasJobs(Protocol):
    @property
    def active_jobs(self) -> Sized: ...


def session_load(max_sessions: int) -> Callable[[_HasJobs], float]:
    """A `load_fnc` reporting active sessions / `max_sessions`, capped at 1.0."""

    def load(server: _HasJobs) -> float:
        return min(1.0, len(server.active_jobs) / max_sessions)

    return load
