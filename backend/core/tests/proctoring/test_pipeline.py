"""The normaliser, the sequence tracker and the episode merge (SP-14). No database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from hirevion_core.proctoring.aggregator import SeqTracker, merge_episode
from hirevion_core.proctoring.catalogue import clean_details
from hirevion_core.proctoring.normaliser import (
    Incoming,
    UnknownEvent,
    check_names,
    normalise,
)
from hirevion_core.proctoring.policy import base_policy

NOW = datetime(2026, 10, 12, 5, 0, tzinfo=UTC)


def incoming(**changes: Any) -> Incoming:
    values: dict[str, Any] = {
        "seq": 1,
        "event": "FACE_ABSENT",
        "source": "camera",
        "started_at": NOW,
    }
    return Incoming(**{**values, **changes})


def test_no_event_carries_what_a_key_typed() -> None:
    details = clean_details(
        {
            "new_app": "chrome.exe",
            "keys": "abc",
            "Keystrokes": ["a"],
            "nested": {"typed_text": "secret", "clipboard": "x", "ok": 1},
            "list": [{"text": "hidden", "n": 2}],
        }
    )
    assert details == {"new_app": "chrome.exe", "nested": {"ok": 1}, "list": [{"n": 2}]}


def test_details_are_bounded() -> None:
    long = clean_details({"window_title": "x" * 5000})
    assert len(long["window_title"]) == 300
    huge = clean_details({f"k{i}": "y" * 290 for i in range(40)})
    assert huge["truncated"] is True
    assert len(str(huge)) < 9000


def test_unknown_events_and_sources_refuse_the_batch() -> None:
    check_names([incoming(), incoming(seq=2, event="WINDOW_MINIMIZED", source="native")])
    for bad in (
        incoming(event="MAKE_COFFEE"),
        incoming(source="satellite"),
        # Events only the server raises can't be sent by a device.
        incoming(event="TELEMETRY_GAP"),
        incoming(event="THIRD_EYE_DISCONNECTED"),
    ):
        with pytest.raises(UnknownEvent):
            check_names([incoming(), bad])


def test_new_event_names_from_the_desktop_are_accepted() -> None:
    check_names(
        [
            incoming(event="DEVICE_CHANGE", source="native"),
            incoming(event="UNEXPECTED_WINDOW", source="native"),
        ]
    )


def test_a_time_far_in_the_future_is_clamped_and_flagged() -> None:
    skewed = normalise(
        incoming(started_at=NOW + timedelta(hours=2)), base_policy("standard"), now=NOW
    )
    assert skewed.started_at == NOW and skewed.details["clock_skew_ms"] == 7_200_000
    fine = normalise(
        incoming(started_at=NOW + timedelta(minutes=1)), base_policy("standard"), now=NOW
    )
    assert fine.started_at == NOW + timedelta(minutes=1) and "clock_skew_ms" not in fine.details


def test_numbers_are_kept_in_range() -> None:
    result = normalise(incoming(duration_ms=-5, confidence=7.0), base_policy("standard"), now=NOW)
    assert result.duration_ms == 0 and result.confidence == 1.0
    assert (
        normalise(incoming(duration_ms=None), base_policy("standard"), now=NOW).duration_ms is None
    )


def test_the_phase_and_the_hint_are_read_from_the_details() -> None:
    result = normalise(
        incoming(details={"phase": "started", "severity_hint": "critical", "level": 2}),
        base_policy("standard"),
        now=NOW,
    )
    assert result.phase == "started" and result.ongoing and result.hint == "CRITICAL"
    odd = normalise(
        incoming(details={"phase": "weird", "severity_hint": "dire"}),
        base_policy("standard"),
        now=NOW,
    )
    assert odd.phase is None and odd.hint is None and not odd.ongoing


def test_a_blocked_processs_category_comes_from_the_policys_rule_not_the_devices_claim() -> None:
    policy = base_policy(
        "standard",
        categories={
            "remote_access": {"severity": "CRITICAL"},
            "messaging": {"severity": "WARNING"},
        },
        blocked=[
            {"match": "publisher", "value": "A", "category": "remote_access"},
            {"match": "publisher", "value": "B", "category": "messaging"},
        ],
    )

    def category(**details: Any) -> str | None:
        item = incoming(event="BLOCKED_PROCESS_DETECTED", source="native", details=details)
        return normalise(item, policy, now=NOW).category

    assert category(rule_index=1, category="remote_access") == "messaging"
    assert category(rule_index=9, category="remote_access") == "remote_access"
    assert category(rule_index=9, category="invented") is None
    assert category() is None


def test_evidence_references_are_kept_small_and_complete() -> None:
    result = normalise(
        incoming(evidence=[{"type": "snapshot", "blob_path": "p"}, {"type": "x"}]),
        base_policy("standard"),
        now=NOW,
    )
    assert result.evidence == [{"type": "snapshot", "blob_path": "p"}]


def test_the_tracker_acks_through_the_first_gap_and_lists_what_is_missing() -> None:
    tracker = SeqTracker()
    assert tracker.offer(1).status == "new" and tracker.acked_through == 1
    opened = tracker.offer(5)
    assert opened.status == "new" and opened.opened_gap == (2, 4)
    assert tracker.acked_through == 1 and tracker.missing() == [2, 3, 4]
    assert tracker.offer(3).status == "fill"
    assert tracker.gaps == [(2, 2), (4, 4)] and tracker.missing() == [2, 4]
    assert tracker.offer(5).status == "duplicate" and tracker.offer(1).status == "duplicate"
    tracker.offer(2)
    tracker.offer(4)
    assert tracker.acked_through == 5 and tracker.missing() == []


def test_a_heartbeats_seq_high_adds_what_has_not_yet_arrived() -> None:
    tracker = SeqTracker(max_seq=10)
    assert tracker.missing(high=12) == [11, 12]
    assert tracker.missing(high=10) == []
    assert SeqTracker(0).missing(high=10_000, limit=3) == [1, 2, 3]


def test_the_tracker_round_trips_and_refuses_wild_numbers() -> None:
    tracker = SeqTracker(9, [[3, 4], [7, 7]])
    again = SeqTracker(tracker.max_seq, tracker.to_json())
    assert again.gaps == [(3, 4), (7, 7)] and again.acked_through == 2
    assert tracker.too_far(0) and tracker.too_far(10**9) and not tracker.too_far(10)


def episode(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "phase": "started",
        "ongoing": True,
        "details": {"phase": "started", "frames": 3},
        "duration_ms": 0,
        "confidence": 0.8,
        "last_seq": 1,
    }
    return {**base, **changes}


def test_an_episode_is_updated_in_place_by_phase() -> None:
    escalated = normalise(
        incoming(
            seq=2, duration_ms=6000, confidence=0.9, details={"phase": "escalated", "level": 2}
        ),
        base_policy("standard"),
        now=NOW,
    )
    update = merge_episode(episode(), escalated)
    assert update["phase"] == "escalated" and update["ongoing"] is True
    assert update["duration_ms"] == 6000 and update["confidence"] == 0.9 and update["last_seq"] == 2
    assert update["details"] == {"phase": "escalated", "frames": 3, "level": 2}
    ended = normalise(
        incoming(seq=3, duration_ms=31_000, details={"phase": "ended", "max_faces": 2}),
        base_policy("standard"),
        now=NOW,
    )
    final = merge_episode(episode(**update), ended)
    assert (
        final["phase"] == "ended" and final["ongoing"] is False and final["duration_ms"] == 31_000
    )


def test_a_late_older_phase_does_not_undo_a_newer_one() -> None:
    late = normalise(
        incoming(seq=2, duration_ms=100, details={"phase": "started", "extra": True}),
        base_policy("standard"),
        now=NOW,
    )
    done = episode(phase="ended", ongoing=False, duration_ms=31_000, last_seq=3)
    update = merge_episode(done, late)
    assert update["phase"] == "ended" and update["ongoing"] is False
    assert update["duration_ms"] == 31_000 and update["last_seq"] == 3
    assert update["details"]["extra"] is True
