"""One attempt per interview (C8-9, owner 2026-11-22): what a candidate may do with an interview
right now — start it, rejoin it once within the reconnect window from the same laptop, or
nothing, because it was taken, is running elsewhere, or isn't open."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from hirevion_core.interview_session.attempts import attempt_of
from hirevion_core.interview_session.briefing import resume_policy
from hirevion_core.interviews.assignment import RESUME_POLICY
from hirevion_core.models import Interview, InterviewSession

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
STRICT = {"grace_seconds": 120, "max_interruptions": 1, "pause_timer": False, "same_device": True}
OLD = {"grace_seconds": 300, "max_interruptions": 3, "pause_timer": True}


def interview(status: str, *, resume: dict[str, Any] | None = None, **fields: Any) -> Interview:
    values: dict[str, Any] = {
        "status": status,
        "starts_at": NOW - timedelta(hours=1),
        "expires_at": NOW + timedelta(hours=1),
        "duration_minutes": 30,
        "interrupted_at": None,
        "policy": {"resume": STRICT if resume is None else resume},
    }
    values.update(fields)
    return Interview(**values)


def session(*, device: str | None = "laptop", interruptions: int = 0) -> InterviewSession:
    return InterviewSession(device_jkt=device, interruptions=interruptions)


def test_new_interviews_get_the_strict_policy() -> None:
    assert RESUME_POLICY == STRICT
    policy = resume_policy({"resume": STRICT})
    assert (policy.grace_seconds, policy.max_interruptions) == (120, 1)
    assert policy.pause_timer is False
    assert policy.same_device is True


def test_an_old_snapshot_keeps_its_rules() -> None:
    policy = resume_policy({"resume": OLD})
    assert policy.same_device is False
    assert resume_policy({}).same_device is False


def test_an_invited_interview_follows_its_window() -> None:
    assert attempt_of(interview("invited"), None, jkt="laptop", now=NOW).state == "available"
    early = interview("invited", starts_at=NOW + timedelta(minutes=5))
    assert attempt_of(early, None, jkt="laptop", now=NOW).state == "not_open"
    late = interview("invited", expires_at=NOW - timedelta(seconds=1))
    assert attempt_of(late, None, jkt="laptop", now=NOW).state == "expired"


@pytest.mark.parametrize(
    "status", ["completed", "evaluating", "evaluated", "abandoned", "cancelled"]
)
def test_a_taken_or_cancelled_interview_is_used(status: str) -> None:
    assert attempt_of(interview(status), session(), jkt="laptop", now=NOW).state == "used"


def test_a_running_interview_can_be_rejoined_from_the_same_laptop() -> None:
    found = attempt_of(interview("in_progress"), session(), jkt="laptop", now=NOW)
    assert found.state == "reconnect"
    assert found.reconnect_until is None


def test_an_interrupted_interview_can_be_rejoined_once_inside_the_window() -> None:
    dropped = NOW - timedelta(seconds=30)
    found = attempt_of(
        interview("interrupted", interrupted_at=dropped),
        session(interruptions=1),
        jkt="laptop",
        now=NOW,
    )
    assert found.state == "reconnect"
    assert found.reconnect_until == dropped + timedelta(seconds=120)


def test_the_window_or_the_count_passing_uses_the_attempt() -> None:
    late = interview("interrupted", interrupted_at=NOW - timedelta(seconds=120))
    assert attempt_of(late, session(interruptions=1), jkt="laptop", now=NOW).state == "used"
    again = interview("interrupted", interrupted_at=NOW - timedelta(seconds=10))
    assert attempt_of(again, session(interruptions=2), jkt="laptop", now=NOW).state == "used"


def test_another_laptop_is_refused_under_the_strict_policy() -> None:
    running = interview("in_progress")
    assert attempt_of(running, session(), jkt="other", now=NOW).state == "elsewhere"
    old = interview("in_progress", resume=OLD)
    assert attempt_of(old, session(), jkt="other", now=NOW).state == "reconnect"


def test_a_running_interview_without_its_session_row_is_used() -> None:
    assert attempt_of(interview("in_progress"), None, jkt="laptop", now=NOW).state == "used"


def test_a_running_interview_past_its_window_end_is_expired() -> None:
    over = interview("in_progress", expires_at=NOW - timedelta(minutes=31), duration_minutes=30)
    assert attempt_of(over, session(), jkt="laptop", now=NOW).state == "expired"
