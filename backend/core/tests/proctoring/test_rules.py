"""The rule engine (SP-14): master plan §6.12's default severities, the policy's overrides,
escalation by repetition, and "never CRITICAL alone" for gaze. No database."""

from __future__ import annotations

from typing import Any

import pytest

from hirevion_core.proctoring.policy import base_policy
from hirevion_core.proctoring.rules import Recent, evaluate

S = 1000


def verdict(event: str, seconds: float | None = None, **options: Any) -> str:
    policy = options.pop("policy", None) or base_policy("strict", single_display=False)
    duration = None if seconds is None else int(seconds * S)
    return evaluate(policy, event, duration_ms=duration, **options).severity


@pytest.mark.parametrize(
    ("event", "seconds", "expected"),
    [
        ("FACE_ABSENT", 4.9, "INFO"),
        ("FACE_ABSENT", 5, "WARNING"),
        ("FACE_ABSENT", 29.9, "WARNING"),
        ("FACE_ABSENT", 30, "CRITICAL"),
        ("MULTIPLE_FACES", 1, "WARNING"),
        ("MULTIPLE_FACES", 3, "CRITICAL"),
        ("UNEXPECTED_PERSON_DETECTED", 2, "WARNING"),
        ("UNEXPECTED_PERSON_DETECTED", 3.5, "CRITICAL"),
        ("PHONE_DETECTED", None, "CRITICAL"),
        ("PHONE_DETECTED", 0, "CRITICAL"),
        ("GAZE_DEVIATION", 2, "INFO"),
        ("GAZE_DEVIATION", 10, "WARNING"),
        ("GAZE_DEVIATION", 600, "WARNING"),
        ("CAMERA_OBSTRUCTED", 4, "WARNING"),
        ("CAMERA_OBSTRUCTED", 5, "CRITICAL"),
        ("CAMERA_DISCONNECTED", 9, "WARNING"),
        ("CAMERA_DISCONNECTED", 10, "CRITICAL"),
        ("MIC_DISCONNECTED", 9, "WARNING"),
        ("MIC_DISCONNECTED", 10, "CRITICAL"),
        ("SCREEN_CAPTURE_STOPPED", 5, "WARNING"),
        ("SCREEN_CAPTURE_STOPPED", 30, "CRITICAL"),
        ("APPLICATION_FOCUS_CHANGE", 2, "INFO"),
        ("APPLICATION_FOCUS_CHANGE", 3, "WARNING"),
        ("APPLICATION_FOCUS_CHANGE", 900, "WARNING"),
        ("WINDOW_MINIMIZED", 2, "INFO"),
        ("WINDOW_MINIMIZED", 4, "WARNING"),
        ("THIRD_EYE_DISCONNECTED", 9, "INFO"),
        ("THIRD_EYE_DISCONNECTED", 10, "WARNING"),
        ("THIRD_EYE_DISCONNECTED", 120, "WARNING"),
        ("CAPTURE_EXCLUDED_WINDOW", None, "CRITICAL"),
        ("REMOTE_SESSION_DETECTED", None, "CRITICAL"),
        ("CLIENT_INTEGRITY_WARNING", None, "CRITICAL"),
        ("VIRTUAL_DEVICE_DETECTED", None, "WARNING"),
        ("ADDITIONAL_SPEAKER_DETECTED", None, "WARNING"),
        ("TELEMETRY_GAP", 300, "WARNING"),
        ("DEVICE_CHANGE", None, "WARNING"),
        ("EXTERNAL_DISPLAY_CHANGE", None, "WARNING"),
        ("VM_DETECTED", None, "INFO"),
        ("CAMERA_RECONNECTED", None, "INFO"),
        ("MIC_RECONNECTED", None, "INFO"),
        ("THIRD_EYE_RECONNECTED", None, "INFO"),
        ("SESSION_INTERRUPTED", None, "INFO"),
        ("SESSION_RESUMED", None, "INFO"),
        ("EDITOR_PASTE", None, "INFO"),
    ],
)
def test_the_default_severities_of_the_master_plan(
    event: str, seconds: float | None, expected: str
) -> None:
    assert verdict(event, seconds) == expected


def test_a_required_third_eye_going_quiet_becomes_critical_after_a_minute() -> None:
    policy = base_policy("strict", third_eye="required")
    assert verdict("THIRD_EYE_DISCONNECTED", 59, policy=policy) == "WARNING"
    assert verdict("THIRD_EYE_DISCONNECTED", 60, policy=policy) == "CRITICAL"


def test_a_single_display_policy_makes_a_second_display_critical() -> None:
    policy = base_policy("standard", single_display=True)
    assert verdict("EXTERNAL_DISPLAY_CHANGE", policy=policy) == "CRITICAL"


def test_a_blocked_process_is_critical_for_a_blocking_category_and_a_warning_otherwise() -> None:
    policy = base_policy(
        "standard",
        categories={
            "remote_access": {"severity": "CRITICAL"},
            "messaging": {"severity": "WARNING"},
        },
    )
    assert (
        verdict("BLOCKED_PROCESS_DETECTED", category="remote_access", policy=policy) == "CRITICAL"
    )
    assert verdict("BLOCKED_PROCESS_DETECTED", category="messaging", policy=policy) == "WARNING"
    assert verdict("BLOCKED_PROCESS_DETECTED", category=None, policy=policy) == "WARNING"
    assert verdict("BLOCKED_PROCESS_DETECTED", category="unheard-of", policy=policy) == "WARNING"


def test_the_policy_can_change_thresholds_and_fix_severities() -> None:
    policy = base_policy(
        "standard",
        overrides={
            "tiers": {"FACE_ABSENT": {"warn_after_ms": 2000, "critical_after_ms": 10000}},
            "fixed": {"VM_DETECTED": "CRITICAL"},
        },
    )
    assert verdict("FACE_ABSENT", 2, policy=policy) == "WARNING"
    assert verdict("FACE_ABSENT", 10, policy=policy) == "CRITICAL"
    assert verdict("VM_DETECTED", policy=policy) == "CRITICAL"
    # Fixing an event's severity replaces its tiers, and the other way round.
    both = base_policy("standard", overrides={"fixed": {"FACE_ABSENT": "INFO"}})
    assert verdict("FACE_ABSENT", 120, policy=both) == "INFO"


def test_events_outside_the_levels_checks_are_only_information() -> None:
    basic = base_policy("basic")  # face and focus only
    assert verdict("PHONE_DETECTED", policy=basic) == "INFO"
    assert verdict("BLOCKED_PROCESS_DETECTED", category="remote_access", policy=basic) == "INFO"
    assert verdict("FACE_ABSENT", 60, policy=basic) == "CRITICAL"
    # What protects the interview itself always applies.
    assert verdict("REMOTE_SESSION_DETECTED", policy=basic) == "CRITICAL"
    assert verdict("SCREEN_CAPTURE_STOPPED", 60, policy=basic) == "CRITICAL"


def test_a_repeated_warning_escalates_but_gaze_never_does() -> None:
    policy = base_policy("standard")
    assert verdict("APPLICATION_FOCUS_CHANGE", 4, recent=Recent(repeats=3), policy=policy) == (
        "WARNING"
    )
    escalated = evaluate(
        policy, "APPLICATION_FOCUS_CHANGE", duration_ms=4 * S, recent=Recent(repeats=4)
    )
    assert escalated.severity == "CRITICAL" and "repeated" in escalated.reasons[-1]
    assert verdict("GAZE_DEVIATION", 20, recent=Recent(repeats=50), policy=policy) == "WARNING"
    # Information isn't escalated by repetition: only warnings are.
    assert (
        verdict("APPLICATION_FOCUS_CHANGE", 1, recent=Recent(repeats=40), policy=policy) == "INFO"
    )


def test_gaze_is_never_critical_alone_and_only_with_corroboration_if_the_policy_allows() -> None:
    corroborated = Recent(corroborating=("evt-1",))
    default = evaluate(
        base_policy("standard"), "GAZE_DEVIATION", duration_ms=60 * S, recent=corroborated
    )
    assert default.severity == "WARNING" and default.corroborated_by == ("evt-1",)

    policy = base_policy("standard", overrides={"gaze": {"critical_when_corroborated": True}})
    alone = evaluate(policy, "GAZE_DEVIATION", duration_ms=60 * S)
    assert alone.severity == "WARNING" and alone.corroborated_by == ()
    together = evaluate(policy, "GAZE_DEVIATION", duration_ms=60 * S, recent=corroborated)
    assert together.severity == "CRITICAL" and together.corroborated_by == ("evt-1",)
    # A short glance with company is still no more than information.
    assert (
        evaluate(policy, "GAZE_DEVIATION", duration_ms=2 * S, recent=corroborated).severity
        == "INFO"
    )


def test_relaxed_gaze_keeps_gaze_at_information() -> None:
    policy = base_policy("standard", accommodations=["relaxed_gaze"])
    assert verdict("GAZE_DEVIATION", 120, policy=policy) == "INFO"


def test_unknown_events_are_information() -> None:
    assert verdict("SOMETHING_NEW", 100) == "INFO"
