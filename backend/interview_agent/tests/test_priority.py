"""Live audio first (perf, 2026-11-24): on a PC at 90% CPU the interviewer's voice detector fell
19 s behind real time and its speech came out slower than it plays, because it ran at the same
priority as the browser and the editor. The interviewer asks the OS to run it first."""

from __future__ import annotations

import sys

import pytest

from hirevion_interview_agent import priority


def test_on_windows_it_asks_to_run_above_background_work(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[int] = []
    monkeypatch.setattr(priority.sys, "platform", "win32")
    monkeypatch.setattr(
        priority, "_set_windows_priority", lambda value: asked.append(value) or True
    )
    assert priority.favour_live_audio() is True
    assert asked == [priority.ABOVE_NORMAL_PRIORITY_CLASS]


def test_elsewhere_it_asks_for_a_little_more_and_carries_on_when_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(priority.sys, "platform", "linux")

    def refuse(*_: int) -> None:
        raise PermissionError("needs CAP_SYS_NICE")

    monkeypatch.setattr(priority.os, "getpriority", lambda *_: 0, raising=False)
    monkeypatch.setattr(priority.os, "setpriority", refuse, raising=False)
    assert priority.favour_live_audio() is False


def test_elsewhere_it_sets_the_value_once_however_often_it_is_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """main() and every job's prewarm call it: the value must not stack to -10, -15..."""
    niceness = [0]
    monkeypatch.setattr(priority.sys, "platform", "linux")
    monkeypatch.setattr(priority.os, "getpriority", lambda *_: niceness[0], raising=False)
    monkeypatch.setattr(
        priority.os,
        "setpriority",
        lambda _w, _p, value: niceness.__setitem__(0, value),
        raising=False,
    )
    assert priority.favour_live_audio() and priority.favour_live_audio()
    assert niceness == [priority.NICE]


@pytest.mark.skipif(sys.platform != "win32", reason="the Windows priority class")
def test_windows_really_raises_the_class() -> None:
    """The stubs above can't see the call itself: an undeclared 64-bit handle made Windows refuse
    it on the owner's PC."""
    try:
        assert priority._set_windows_priority(priority.ABOVE_NORMAL_PRIORITY_CLASS) is True
        assert priority._priority_class() == priority.ABOVE_NORMAL_PRIORITY_CLASS
    finally:
        priority._set_windows_priority(priority.NORMAL_PRIORITY_CLASS)
