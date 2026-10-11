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
from uuid import UUID

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


def gap_payload(
    interview_id: UUID,
    track: str,
    *,
    kind: str,
    state: str,
    from_seq: int,
    to_seq: int | None,
    from_time: datetime | None,
    to_time: datetime | None,
    **extra: Any,
) -> dict[str, Any]:
    """The `recording.gap` outbox event (SP-14 turns it into `SCREEN_CAPTURE_STOPPED` or
    `TELEMETRY_GAP`).

    - `kind` is `stalled` (a track went silent for longer than its policy allows), or, once the
      track is assembled, `missing` (numbers never acknowledged) or `corrupt` (numbers whose
      blob no longer matched its acknowledged hash, or was gone).
    - `state` is `open` while a stall lasts, and `closed` once it ended; `to_seq` and `to_time`
      are null until then. A closed stall's `to_seq` is the last number that didn't arrive in
      time, so `to_seq < from_seq` means the segments came, but late.
    - Times are server time, ISO 8601.
    """
    payload: dict[str, Any] = {
        "interview_id": str(interview_id),
        "track": track,
        "kind": kind,
        "state": state,
        "from_seq": from_seq,
        "to_seq": to_seq,
        "from_time": from_time.isoformat() if from_time else None,
        "to_time": to_time.isoformat() if to_time else None,
    }
    for name, value in extra.items():
        payload[name] = value.isoformat() if isinstance(value, datetime) else value
    return payload


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
