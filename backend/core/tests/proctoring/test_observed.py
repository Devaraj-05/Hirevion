"""Server-observed state: votes from several sources, a debounce, and an event that grows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from hirevion_core.proctoring import observed as obs

T0 = datetime(2026, 10, 12, 5, 0, 0, tzinfo=UTC)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def test_a_channel_is_down_while_any_source_says_so() -> None:
    state: dict[str, Any] = {}
    assert obs.state_of(state, "camera") == "unknown"
    assert obs.vote(state, "camera", "heartbeat", "up", at(0)) is True
    assert obs.state_of(state, "camera") == "up"
    assert obs.vote(state, "camera", "livekit", "down", at(5)) is True
    # The desktop saying "on" doesn't undo what LiveKit saw.
    assert obs.vote(state, "camera", "heartbeat", "up", at(6)) is False
    assert obs.state_of(state, "camera") == "down"
    assert obs.down_since(state, "camera") == at(5)
    assert obs.vote(state, "camera", "livekit", "up", at(30)) is True
    assert obs.state_of(state, "camera") == "up" and obs.recovered_at(state, "camera") == at(30)


def test_a_late_webhook_does_not_overwrite_a_newer_view() -> None:
    state: dict[str, Any] = {}
    obs.vote(state, "mic", "livekit", "up", at(10))
    assert obs.vote(state, "mic", "livekit", "down", at(5)) is False
    assert obs.state_of(state, "mic") == "up"


def test_a_channel_opens_an_event_only_after_the_debounce_then_updates_then_closes() -> None:
    state: dict[str, Any] = {}
    obs.vote(state, "screen", "livekit", "down", at(0))
    assert obs.step(state, "screen", at(2), 5).action == "none"
    opened = obs.step(state, "screen", at(5), 5)
    assert opened.action == "open" and opened.started_at == at(0)
    obs.set_event(state, "screen", "evt-1")
    assert obs.step(state, "screen", at(20), 5).action == "update"
    obs.vote(state, "screen", "livekit", "up", at(31))
    closing = obs.step(state, "screen", at(32), 5)
    assert closing.action == "close" and closing.ended_at == at(31)
    obs.set_event(state, "screen", None)
    assert obs.step(state, "screen", at(40), 5).action == "none"
    assert obs.down_since(state, "screen") is None


def test_a_flap_inside_the_debounce_raises_nothing() -> None:
    state: dict[str, Any] = {}
    obs.vote(state, "camera", "livekit", "down", at(0))
    obs.vote(state, "camera", "livekit", "up", at(2))
    assert obs.step(state, "camera", at(3), 5).action == "clear"
    obs.set_event(state, "camera", None)
    assert obs.step(state, "camera", at(10), 5).action == "none"


def test_a_missed_heartbeat_needs_no_further_debounce() -> None:
    state: dict[str, Any] = {}
    obs.vote(state, "heartbeat", "beat", "up", at(0))
    obs.vote(state, "heartbeat", "beat", "down", at(0))
    step = obs.step(state, "heartbeat", at(21), 5)
    assert step.action == "open" and step.started_at == at(0)


def test_reset_forgets_old_views() -> None:
    state: dict[str, Any] = {}
    obs.vote(state, "camera", "livekit", "down", at(0))
    obs.reset(state)
    assert obs.state_of(state, "camera") == "unknown" and obs.down_since(state, "camera") is None


def test_every_down_event_has_a_channel() -> None:
    assert obs.CHANNEL_OF_EVENT["CAMERA_DISCONNECTED"] == "camera"
    assert obs.CHANNEL_OF_EVENT["SCREEN_CAPTURE_STOPPED"] == "screen"
    assert obs.CHANNEL_OF_EVENT["TELEMETRY_GAP"] == "heartbeat"
