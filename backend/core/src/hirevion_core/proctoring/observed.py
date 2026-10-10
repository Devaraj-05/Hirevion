"""Server-observed state (master plan decision D11: what the server sees is the ground truth).

Each channel (camera, microphone, screen capture, the third eye, the heartbeat itself) gets
*votes* from independent sources: the desktop's heartbeat, LiveKit's webhooks, upload continuity.
A channel is down while any source says so, so a client that stops reporting a problem, or
reports it falsely as fixed, doesn't change what LiveKit saw. A channel must stay down for a
short debounce before it becomes an event, and then its severity grows with its duration.

This module is the state machine on the stored `observed` dictionary; `service` turns what it
decides into events.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

State = Literal["up", "down", "unknown"]


@dataclass(frozen=True, slots=True)
class Channel:
    name: str
    down_event: str
    up_event: str | None
    source: str
    """The event's `source`."""
    debounce: bool = True
    """False when the channel's own rule already waited (a missed heartbeat)."""


CHANNELS: dict[str, Channel] = {
    "camera": Channel("camera", "CAMERA_DISCONNECTED", "CAMERA_RECONNECTED", "camera"),
    "mic": Channel("mic", "MIC_DISCONNECTED", "MIC_RECONNECTED", "audio"),
    "screen": Channel("screen", "SCREEN_CAPTURE_STOPPED", None, "screen"),
    "third_eye": Channel(
        "third_eye", "THIRD_EYE_DISCONNECTED", "THIRD_EYE_RECONNECTED", "third_eye"
    ),
    "heartbeat": Channel("heartbeat", "TELEMETRY_GAP", None, "interview", debounce=False),
}
# The channel each event of a device shows up on (a device's own report of it).
CHANNEL_OF_EVENT = {channel.down_event: name for name, channel in CHANNELS.items()}


def _iso(at: datetime) -> str:
    return at.astimezone(UTC).isoformat()


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _channel(observed: dict[str, Any], name: str) -> dict[str, Any]:
    channel: dict[str, Any] = observed.setdefault(
        name, {"votes": {}, "down_since": None, "event_id": None}
    )
    return channel


def state_of(observed: dict[str, Any], name: str) -> State:
    votes = (observed.get(name) or {}).get("votes") or {}
    states = {vote["state"] for vote in votes.values()}
    if "down" in states:
        return "down"
    return "up" if "up" in states else "unknown"


def vote(observed: dict[str, Any], name: str, source: str, state: State, at: datetime) -> bool:
    """Records `source`'s latest view of channel `name`; ignores a view older than the one it
    already holds (webhooks can arrive late or out of order). True if the channel's combined
    state changed."""
    channel = _channel(observed, name)
    held = channel["votes"].get(source)
    if held is not None and _parse(held["at"]) > at:  # type: ignore[operator]
        return False
    before = state_of(observed, name)
    if state == "unknown":
        channel["votes"].pop(source, None)
    else:
        channel["votes"][source] = {"state": state, "at": _iso(at)}
    after = state_of(observed, name)
    if after == "down" and before != "down":
        channel["down_since"] = _iso(at)
    elif before == "down" and after != "down":
        channel["recovered_at"] = _iso(at)
    return after != before


def down_since(observed: dict[str, Any], name: str) -> datetime | None:
    return _parse((observed.get(name) or {}).get("down_since"))


def recovered_at(observed: dict[str, Any], name: str) -> datetime | None:
    return _parse((observed.get(name) or {}).get("recovered_at"))


def event_id(observed: dict[str, Any], name: str) -> str | None:
    return (observed.get(name) or {}).get("event_id")


def set_event(observed: dict[str, Any], name: str, value: str | None) -> None:
    channel = _channel(observed, name)
    channel["event_id"] = value
    if value is None:
        channel["down_since"] = None
        channel["recovered_at"] = None


def reset(observed: dict[str, Any]) -> None:
    """Forgets every vote (the candidate left or came back: old views no longer hold)."""
    for channel in observed.values():
        if isinstance(channel, dict) and "votes" in channel:
            channel["votes"] = {}
            channel["down_since"] = None


@dataclass(frozen=True, slots=True)
class Step:
    """What a channel needs now."""

    action: Literal["none", "open", "update", "close", "clear"]
    started_at: datetime | None = None
    ended_at: datetime | None = None


def step(observed: dict[str, Any], name: str, now: datetime, observe_seconds: float) -> Step:
    """The channel's next move at `now`: open an event once it has been down long enough, keep a
    long one growing, close one that came back, or forget a short flap."""
    channel = CHANNELS[name]
    state = state_of(observed, name)
    since = down_since(observed, name)
    open_event = event_id(observed, name)
    if state == "down" and since is not None:
        if open_event is not None:
            return Step("update", since, now)
        waited = (now - since).total_seconds()
        if not channel.debounce or waited >= observe_seconds:
            return Step("open", since, now)
        return Step("none")
    if open_event is not None and state != "down":
        return Step("close", since, recovered_at(observed, name) or now)
    if open_event is None and since is not None:
        return Step("clear")
    return Step("none")
