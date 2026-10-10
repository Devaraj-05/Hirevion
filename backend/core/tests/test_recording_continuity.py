"""When a track counts as stalled (SP-12 continuity), as pure rules."""

from datetime import UTC, datetime, timedelta

import pytest

from hirevion_core.recordings.continuity import (
    ALLOWED_SILENCE_SECONDS,
    TrackState,
    allowed_silence,
    find_stalls,
)

START = datetime(2026, 10, 12, 5, 0, 0, tzinfo=UTC)


def at(seconds: float) -> datetime:
    return START + timedelta(seconds=seconds)


def state(
    track: str, last_seq: int | None, arrived: float | None, *, stalled: bool = False
) -> TrackState:
    return TrackState(
        track,
        last_seq,
        last_end=at(arrived) if arrived is not None else None,
        last_arrival=at(arrived) if arrived is not None else None,
        stalled=stalled,
    )


def steady(arrived: float) -> dict[str, TrackState]:
    return {t: state(t, 5, arrived) for t in ("screen-1", "camera", "mic")}


@pytest.mark.parametrize(
    ("level", "seconds"), [("off", 120), ("basic", 60), ("standard", 30), ("strict", 20)]
)
def test_the_allowed_silence_follows_the_proctoring_level(level: str, seconds: int) -> None:
    assert allowed_silence({"proctoring_level": level}) == seconds
    assert ALLOWED_SILENCE_SECONDS[level] == seconds


def test_an_unknown_level_gets_the_standard_allowance() -> None:
    assert allowed_silence({}) == 30
    assert allowed_silence({"proctoring_level": "paranoid"}) == 30


def test_no_stall_while_segments_keep_arriving() -> None:
    assert find_stalls({}, steady(100), started_at=at(0), connected_at=None, now=at(120)) == []


def test_a_track_silent_for_longer_than_allowed_is_stalled_with_where_it_stopped() -> None:
    states = steady(100)
    states["screen-1"] = state("screen-1", 9, 60)
    (stall,) = find_stalls({}, states, started_at=at(0), connected_at=None, now=at(100))
    assert stall.track == "screen-1"
    assert stall.from_seq == 10
    assert stall.from_time == at(60)  # where its last segment ended
    assert (stall.silent_seconds, stall.allowed_seconds) == (40, 30)


def test_exactly_the_allowance_is_still_fine() -> None:
    states = {
        "screen-1": state("screen-1", 9, 60),
        **{k: v for k, v in steady(90).items() if k != "screen-1"},
    }
    assert find_stalls({}, states, started_at=at(0), connected_at=None, now=at(90)) == []


def test_a_stall_already_reported_is_not_reported_again() -> None:
    states = steady(195)
    states["mic"] = state("mic", 9, 10, stalled=True)
    assert find_stalls({}, states, started_at=at(0), connected_at=None, now=at(200)) == []


def test_a_required_track_that_never_started_stalls_from_the_interview_start() -> None:
    states = {t: state(t, 3, 20) for t in ("screen-1", "camera")}  # no mic at all
    (stall,) = find_stalls({}, states, started_at=at(0), connected_at=None, now=at(40))
    assert (stall.track, stall.from_seq, stall.from_time) == ("mic", 0, at(0))


def test_a_track_the_policy_does_not_record_is_never_watched() -> None:
    policy = {"recording": {"camera": False, "audio": False}}
    states = {"screen-1": state("screen-1", 3, 20)}
    assert find_stalls(policy, states, started_at=at(0), connected_at=None, now=at(40)) == []


def test_a_resumed_interview_is_not_flagged_for_the_time_it_was_away() -> None:
    states = steady(100)  # last segments arrived at 100 s, then the candidate dropped out
    assert find_stalls({}, states, started_at=at(0), connected_at=at(400), now=at(410)) == []
    (first, *_) = find_stalls({}, states, started_at=at(0), connected_at=at(400), now=at(440))
    assert first.silent_seconds == 40


def test_a_second_display_is_watched_once_it_has_produced_a_segment() -> None:
    states = steady(100)
    states["screen-2"] = state("screen-2", 1, 20)
    stalls = find_stalls({}, states, started_at=at(0), connected_at=None, now=at(100))
    assert [s.track for s in stalls] == ["screen-2"]


def test_the_allowance_is_never_below_two_segments() -> None:
    assert allowed_silence({"proctoring_level": "strict"}) >= 20
