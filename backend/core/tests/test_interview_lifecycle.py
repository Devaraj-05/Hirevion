"""The interview state machine's transition table (SP-07a Task 2); no database needed."""

import pytest

from hirevion_core.access.errors import Conflict
from hirevion_core.interviews.lifecycle import TRANSITIONS, can_transition, require_transition
from hirevion_core.models.interview import INTERVIEW_STATUSES

ALLOWED = {
    ("scheduled", "invited"),
    ("scheduled", "cancelled"),
    ("scheduled", "expired"),
    ("invited", "invited"),
    ("invited", "in_progress"),
    ("invited", "cancelled"),
    ("invited", "expired"),
    ("in_progress", "interrupted"),
    ("in_progress", "completed"),
    ("in_progress", "abandoned"),
    ("interrupted", "in_progress"),
    ("interrupted", "completed"),
    ("interrupted", "abandoned"),
    ("completed", "evaluating"),
    ("evaluating", "evaluated"),
    ("evaluating", "completed"),
    ("evaluated", "evaluating"),
    ("expired", "invited"),
}


def test_every_status_has_a_row() -> None:
    assert set(TRANSITIONS) == set(INTERVIEW_STATUSES)


@pytest.mark.parametrize("source", INTERVIEW_STATUSES)
@pytest.mark.parametrize("target", INTERVIEW_STATUSES)
def test_the_table_is_exactly_the_documented_one(source: str, target: str) -> None:
    assert can_transition(source, target) == ((source, target) in ALLOWED)


def test_a_refused_move_is_a_conflict_naming_both_ends() -> None:
    with pytest.raises(Conflict) as caught:
        require_transition("cancelled", "invited")
    assert caught.value.code == "invalid-transition"
    assert "cancelled" in caught.value.title and "invited" in caught.value.title


def test_ended_interviews_go_nowhere() -> None:
    for ended in ("cancelled", "abandoned"):
        assert TRANSITIONS[ended] == frozenset()
