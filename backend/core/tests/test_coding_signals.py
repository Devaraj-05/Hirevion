"""The coding console's integrity signals (SP-16, PRD §48): what the events add up to, in words a
reviewer reads as a signal, never as proof."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hirevion_core.coding.signals import Event, integrity_signals

ASKED = datetime(2026, 10, 23, 10, 0, tzinfo=UTC)


def at(seconds: float) -> datetime:
    return ASKED + timedelta(seconds=seconds)


def test_nothing_recorded_says_so() -> None:
    signals = integrity_signals([], final_chars=0, closed_at=at(600))
    assert signals.events == 0 and signals.notable is False
    assert signals.statements == ["No console activity was recorded."]


def test_pastes_copies_typing_and_time_away_add_up() -> None:
    events = [
        Event("focus", at(1)),
        Event("typing_started", at(5)),
        Event("typing_stopped", at(65)),
        Event("blur", at(70)),
        Event("focus", at(130)),
        Event("paste", at(131), 300),
        Event("paste", at(140), 100),
        Event("copy", at(150), 20),
        Event("cut", at(151), 5),
        Event("typing_started", at(160)),
        Event("blur", at(200)),
    ]
    signals = integrity_signals(events, final_chars=500, closed_at=at(230))
    body = signals.as_json()
    assert body["pastes"] == 2 and body["pasted_chars"] == 400 and body["largest_paste"] == 300
    assert body["copies"] == 1 and body["cuts"] == 1
    assert body["paste_share"] == 0.8
    assert body["blurs"] == 2 and body["time_away_seconds"] == 90  # 60 s, then 30 s to the end
    assert body["typing_seconds"] == 100  # 60 s, then 40 s until it left the box
    assert signals.notable is True
    assert "Pasted 2 times, 400 characters in all (the largest 300)." in signals.statements
    assert "Pasted text adds up to 80% of the final code's length." in signals.statements
    assert "Left the code box 2 times, about 90 seconds in all." in signals.statements


def test_code_that_only_arrived_by_paste_is_described_not_judged() -> None:
    signals = integrity_signals([Event("paste", at(10), 900)], final_chars=900, closed_at=at(60))
    assert signals.paste_share == 1.0 and signals.notable
    assert "No typing was recorded; the code arrived by paste." in signals.statements
    assert not any("cheat" in s.lower() or "copied from" in s.lower() for s in signals.statements)


def test_typing_alone_is_quiet() -> None:
    events = [Event("typing_started", at(1)), Event("typing_stopped", at(300))]
    signals = integrity_signals(events, final_chars=400, closed_at=at(310))
    assert signals.notable is False and signals.paste_share == 0.0
    assert signals.statements == ["Typed for about 299 seconds; nothing was pasted."]
