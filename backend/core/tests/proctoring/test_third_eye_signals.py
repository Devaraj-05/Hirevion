"""PRD §53's other third-eye signals and cross-camera correlation (C7-2, 2026-11-26): what each
new event weighs by default, and an episode both cameras saw at about the same time carrying the
other camera's event as backing. Signals stay evidence, never proof. No database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hirevion_core.proctoring.catalogue import EVENTS
from hirevion_core.proctoring.policy import base_policy
from hirevion_core.proctoring.rules import Recent, evaluate
from hirevion_core.proctoring.store import History, recent_for
from hirevion_core.reports.labels import EVENT_LABELS, SECTION_OF_EVENT
from hirevion_core.reports.proctoring import explain

S = 1000
NEW = (
    "SECONDARY_SCREEN_DETECTED",
    "CANDIDATE_LEFT_VIEW",
    "HANDS_OUT_OF_VIEW",
    "UNUSUAL_MOVEMENT",
    "THIRD_EYE_VIEW_CHANGED",
)
T0 = datetime(2026, 11, 26, 10, 0, tzinfo=UTC)


def severity(event: str, seconds: float, level: str = "strict") -> str:
    policy = base_policy(level, single_display=False)
    return evaluate(policy, event, duration_ms=int(seconds * S)).severity


CHECKS = {
    "SECONDARY_SCREEN_DETECTED": "displays",
    "CANDIDATE_LEFT_VIEW": "face",
    "HANDS_OUT_OF_VIEW": "third_eye",
    "UNUSUAL_MOVEMENT": "third_eye",
    # The phone turned away defeats the third eye itself: always checked while it is on.
    "THIRD_EYE_VIEW_CHANGED": None,
}


def test_the_new_signals_come_from_the_third_eye_under_the_fitting_check() -> None:
    for name in NEW:
        assert EVENTS[name].source == "third_eye"
        assert EVENTS[name].check == CHECKS[name]
        assert EVENTS[name].client is False
        assert name in EVENT_LABELS and name in SECTION_OF_EVENT


@pytest.mark.parametrize(
    ("event", "seconds", "expected"),
    [
        ("SECONDARY_SCREEN_DETECTED", 5, "WARNING"),
        ("SECONDARY_SCREEN_DETECTED", 600, "WARNING"),
        ("CANDIDATE_LEFT_VIEW", 9, "INFO"),
        ("CANDIDATE_LEFT_VIEW", 10, "WARNING"),
        ("CANDIDATE_LEFT_VIEW", 60, "CRITICAL"),
        ("HANDS_OUT_OF_VIEW", 14, "INFO"),
        ("HANDS_OUT_OF_VIEW", 15, "WARNING"),
        ("HANDS_OUT_OF_VIEW", 900, "WARNING"),
        ("UNUSUAL_MOVEMENT", 3.9, "INFO"),
        ("UNUSUAL_MOVEMENT", 4, "WARNING"),
        ("THIRD_EYE_VIEW_CHANGED", 5, "WARNING"),
    ],
)
def test_default_weights(event: str, seconds: float, expected: str) -> None:
    assert severity(event, seconds) == expected


def test_each_signal_is_a_warning_by_the_time_the_vision_agent_records_it() -> None:
    """The agent's holds reach each warning tier, so an episode alerts live (review)."""
    from hirevion_vision_agent.watch import EVENTS, HOLD_SECONDS

    for kind, event in EVENTS.items():
        assert severity(event, HOLD_SECONDS[kind]) in ("WARNING", "CRITICAL"), event


def test_a_level_without_the_third_eye_check_keeps_them_as_information() -> None:
    assert severity("SECONDARY_SCREEN_DETECTED", 60, level="basic") == "INFO"


def row(event: str, source: str, seconds: float, row_id: str) -> History:
    return (event, "CRITICAL", T0 + timedelta(seconds=seconds), row_id, source)


def test_both_cameras_seeing_a_second_person_back_each_other() -> None:
    policy = base_policy("strict")
    rows = [row("MULTIPLE_FACES", "camera", 2, "cam-1"), row("FACE_ABSENT", "camera", 3, "x")]
    recent = recent_for(policy, rows, "UNEXPECTED_PERSON_DETECTED", T0, source="third_eye")
    assert recent.cross_camera == ("cam-1",)


def test_the_same_camera_or_a_distant_time_is_not_backing() -> None:
    policy = base_policy("strict")
    same = [row("PHONE_DETECTED", "third_eye", 1, "eye-1")]
    assert recent_for(policy, same, "PHONE_DETECTED", T0, source="third_eye").cross_camera == ()
    far = [row("PHONE_DETECTED", "camera", 45, "cam-9")]
    assert recent_for(policy, far, "PHONE_DETECTED", T0, source="third_eye").cross_camera == ()
    near = [row("PHONE_DETECTED", "camera", -8, "cam-2")]
    assert recent_for(policy, near, "PHONE_DETECTED", T0, source="third_eye").cross_camera == (
        "cam-2",
    )


def test_the_candidate_gone_from_both_cameras_backs_each_other() -> None:
    policy = base_policy("strict")
    rows = [row("FACE_ABSENT", "camera", 4, "cam-3")]
    recent = recent_for(policy, rows, "CANDIDATE_LEFT_VIEW", T0, source="third_eye")
    assert recent.cross_camera == ("cam-3",)


def test_backing_is_recorded_without_changing_the_weight() -> None:
    policy = base_policy("strict")
    alone = evaluate(policy, "PHONE_DETECTED", duration_ms=2 * S)
    backed = evaluate(
        policy, "PHONE_DETECTED", duration_ms=2 * S, recent=Recent(cross_camera=("cam-2",))
    )
    assert backed.severity == alone.severity
    assert backed.corroborated_by == ("cam-2",)
    assert "both-cameras" in backed.reasons
    assert "seen by both cameras" in explain(backed.reasons)
