"""Recording continuity (SP-12): when a track has been silent for longer than its interview's
policy allows. The rules are pure; `monitor.py` runs them over the interviews in progress.

A track is "silent" while no segment of it has *arrived* (an upload URL was asked for). That
says the stream stopped reaching the server, not why: the proctoring engine (SP-14) decides
whether it is a violation (`SCREEN_CAPTURE_STOPPED`, `TELEMETRY_GAP`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from hirevion_core.recordings import tracks

SEGMENT_SECONDS = 10
# How long a track may be silent, by the interview's pinned proctoring level.
ALLOWED_SILENCE_SECONDS: dict[str, int] = {"off": 120, "basic": 60, "standard": 30, "strict": 20}
DEFAULT_LEVEL = "standard"
# Never less than two segments, whatever the table says.
FLOOR_SECONDS = 2 * SEGMENT_SECONDS


def allowed_silence(policy: Mapping[str, Any]) -> int:
    level = policy.get("proctoring_level")
    seconds = ALLOWED_SILENCE_SECONDS.get(
        level if isinstance(level, str) else DEFAULT_LEVEL, ALLOWED_SILENCE_SECONDS[DEFAULT_LEVEL]
    )
    return max(FLOOR_SECONDS, seconds)


def shortest_silence() -> int:
    """The smallest allowance of any level: interviews that haven't been quiet that long needn't
    be looked at."""
    return max(FLOOR_SECONDS, min(ALLOWED_SILENCE_SECONDS.values()))


@dataclass(frozen=True, slots=True)
class TrackState:
    track: str
    last_seq: int | None
    last_end: datetime | None  # when the last segment's recording ended (device time, as sent)
    last_arrival: datetime | None  # when the server last heard of a segment of this track
    stalled: bool  # a stall was already reported and no segment has arrived since


@dataclass(frozen=True, slots=True)
class Stall:
    track: str
    from_seq: int
    from_time: datetime
    silent_seconds: int
    allowed_seconds: int


def find_stalls(
    policy: Mapping[str, Any],
    states: Mapping[str, TrackState],
    *,
    started_at: datetime,
    connected_at: datetime | None,
    now: datetime,
) -> list[Stall]:
    """The tracks newly silent for longer than `policy` allows.

    The silence is counted from the latest of the track's last arrival, the interview's start
    and the candidate's last connection, so a resumed interview isn't flagged for the time it
    was away. Tracks the policy doesn't record are never watched; the required ones are watched
    from the start even if they never produced a segment.
    """
    allowed = allowed_silence(policy)
    watched = tracks.expected_tracks(policy)
    watched += [t for t in states if t not in watched and tracks.is_recorded(policy, t)]
    stalls: list[Stall] = []
    for track in sorted(watched, key=tracks.track_order):
        state = states.get(track)
        if state is not None and state.stalled:
            continue
        moments = [started_at, connected_at, state.last_arrival if state is not None else None]
        reference = max(m for m in moments if m is not None)
        silent = int((now - reference).total_seconds())
        if silent <= allowed:
            continue
        last_seq = state.last_seq if state is not None else None
        from_time = state.last_end if state is not None and state.last_end else started_at
        stalls.append(
            Stall(
                track=track,
                from_seq=0 if last_seq is None else last_seq + 1,
                from_time=from_time,
                silent_seconds=silent,
                allowed_seconds=allowed,
            )
        )
    return stalls
