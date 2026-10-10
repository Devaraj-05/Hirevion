"""The rule engine (PRD §64, master plan §6.12): from the session's pinned policy, the event and
what happened lately to a severity with the reasons for it. Pure: no database.

The server decides. A device may suggest a severity (`severity_hint`), but it is only kept as a
note. Severity comes from, in order:

1. the policy's checks: an event the level doesn't cover is only information;
2. a fixed severity, or duration tiers (information below `warn_after_ms`, a warning from it and
   critical from `critical_after_ms`);
3. special cases: a blocked process in a blocking category, a second display under a
   single-display policy;
4. escalation: a warning that has recurred often enough inside the window becomes critical;
5. gaze, which is never critical on its own.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from hirevion_core.proctoring.catalogue import RANK, check_enabled

# (warn_after_ms, critical_after_ms): None means "never reaches that level".
Tier = tuple[int | None, int | None]
DEFAULT_TIERS: dict[str, Tier] = {
    "FACE_ABSENT": (5_000, 30_000),
    "MULTIPLE_FACES": (0, 3_000),
    "UNEXPECTED_PERSON_DETECTED": (0, 3_000),
    "PHONE_DETECTED": (0, 0),
    "GAZE_DEVIATION": (10_000, None),
    "CAMERA_OBSTRUCTED": (0, 5_000),
    "FACE_TOO_FAR": (10_000, None),
    "FACE_TOO_CLOSE": (10_000, None),
    "CAMERA_DISCONNECTED": (0, 10_000),
    "MIC_DISCONNECTED": (0, 10_000),
    "SCREEN_CAPTURE_STOPPED": (0, 30_000),
    "APPLICATION_FOCUS_CHANGE": (3_000, None),
    "WINDOW_MINIMIZED": (3_000, None),
    "UNEXPECTED_WINDOW": (3_000, None),
    "EDITOR_FOCUS_CHANGE": (3_000, None),
    "THIRD_EYE_DISCONNECTED": (10_000, None),
}
REQUIRED_THIRD_EYE_TIER: Tier = (10_000, 60_000)
DEFAULT_FIXED: dict[str, str] = {
    "EXTERNAL_DISPLAY_CHANGE": "WARNING",
    "BLOCKED_PROCESS_DETECTED": "WARNING",
    "DEVICE_CHANGE": "WARNING",
    "CAPTURE_EXCLUDED_WINDOW": "CRITICAL",
    "REMOTE_SESSION_DETECTED": "CRITICAL",
    "CLIENT_INTEGRITY_WARNING": "CRITICAL",
    "VIRTUAL_DEVICE_DETECTED": "WARNING",
    "ADDITIONAL_SPEAKER_DETECTED": "WARNING",
    "TELEMETRY_GAP": "WARNING",
    "VM_DETECTED": "INFO",
    "CAMERA_RECONNECTED": "INFO",
    "MIC_RECONNECTED": "INFO",
    "THIRD_EYE_RECONNECTED": "INFO",
    "SESSION_INTERRUPTED": "INFO",
    "SESSION_RESUMED": "INFO",
    "EDITOR_PASTE": "INFO",
}
# Warnings of these kinds that keep recurring become critical (the policy can change the list,
# the count and the window). Gaze is deliberately absent.
DEFAULT_ESCALATION: dict[str, Any] = {
    "repeat_count": 5,
    "window_seconds": 600,
    "events": [
        "FACE_ABSENT",
        "FACE_TOO_FAR",
        "FACE_TOO_CLOSE",
        "APPLICATION_FOCUS_CHANGE",
        "WINDOW_MINIMIZED",
        "UNEXPECTED_WINDOW",
        "EDITOR_FOCUS_CHANGE",
        "EXTERNAL_DISPLAY_CHANGE",
        "DEVICE_CHANGE",
        "VIRTUAL_DEVICE_DETECTED",
    ],
}
DEFAULT_GAZE: dict[str, Any] = {"critical_when_corroborated": False, "corroboration_seconds": 30}
GAZE = "GAZE_DEVIATION"


@dataclass(frozen=True, slots=True)
class Recent:
    """What happened lately in the session, as the rule engine needs it."""

    repeats: int = 0
    """Events of the same name at WARNING or above inside the escalation window."""
    corroborating: tuple[str, ...] = ()
    """Ids of other events (not gaze) at WARNING or above near this one in time."""


@dataclass(frozen=True, slots=True)
class Verdict:
    severity: str
    reasons: tuple[str, ...] = ()
    corroborated_by: tuple[str, ...] = ()


def _by_duration(tier: Mapping[str, Any], duration_ms: int) -> str:
    critical = tier.get("critical_after_ms")
    warn = tier.get("warn_after_ms")
    if critical is not None and duration_ms >= int(critical):
        return "CRITICAL"
    if warn is not None and duration_ms >= int(warn):
        return "WARNING"
    return "INFO"


def _base(policy: Mapping[str, Any], event: str, duration_ms: int) -> tuple[str, str]:
    fixed = (policy.get("fixed") or {}).get(event)
    if fixed in RANK:
        return str(fixed), f"fixed:{fixed}"
    tier = (policy.get("tiers") or {}).get(event)
    if tier is None:
        return "INFO", "unlisted"
    severity = _by_duration(tier, duration_ms)
    return severity, f"duration:{duration_ms}ms"


def evaluate(
    policy: Mapping[str, Any],
    event: str,
    *,
    duration_ms: int | None,
    category: str | None = None,
    recent: Recent = Recent(),  # noqa: B008 (immutable)
) -> Verdict:
    if not check_enabled(event, list(policy.get("checks") or [])):
        return Verdict("INFO", ("check-off",))
    duration = max(0, duration_ms or 0)
    severity, why = _base(policy, event, duration)
    reasons = [why]

    if event == "BLOCKED_PROCESS_DETECTED" and category is not None:
        rule = (policy.get("categories") or {}).get(category)
        if rule and rule.get("severity") == "CRITICAL":
            severity, reasons = "CRITICAL", [f"category:{category}"]
    if event == "EXTERNAL_DISPLAY_CHANGE" and policy.get("single_display"):
        severity, reasons = "CRITICAL", ["single-display"]

    escalation = policy.get("escalation") or {}
    if (
        severity == "WARNING"
        and event in (escalation.get("events") or [])
        and event != GAZE
        and recent.repeats + 1 >= int(escalation.get("repeat_count") or 0) > 0
    ):
        severity = "CRITICAL"
        reasons.append(f"repeated:{recent.repeats + 1} in {escalation.get('window_seconds')}s")

    corroborated: tuple[str, ...] = ()
    if event == GAZE:
        corroborated = recent.corroborating
        if severity == "CRITICAL":
            severity = "WARNING"
            reasons.append("capped:gaze")
        allow = (policy.get("gaze") or {}).get("critical_when_corroborated")
        if allow and corroborated and severity == "WARNING":
            severity = "CRITICAL"
            reasons.append("corroborated")
    return Verdict(severity, tuple(reasons), corroborated)
