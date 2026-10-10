"""The proctoring policy a session is pinned to (PRD §61, §64; master plan §6.12).

`build_policy` reads the interview's snapshot (SP-07a: the level, its checks, the third-eye
requirement and the approved accommodations), the platform catalogue of application rules and
the organisation's own, and writes one self-contained dictionary. The proctor session stores it
when it opens, so editing the catalogue or the template later never changes a running interview,
and every event carries the policy version it was judged under.

`session_view` shapes the part the desktop needs for `POST /proctoring/session`; the severity
tiers go with it so the device can apply the same temporal thresholds before it reports.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.interviews.templates import PROCTORING_PRESETS
from hirevion_core.models import AppCategory, AppRule, Interview
from hirevion_core.proctoring.rules import (
    DEFAULT_ESCALATION,
    DEFAULT_FIXED,
    DEFAULT_GAZE,
    DEFAULT_TIERS,
    REQUIRED_THIRD_EYE_TIER,
)

PROCTOR_POLICY_VERSION = 1
HEARTBEAT_SECONDS = 5
HEARTBEAT_GRACE_SECONDS = 20
"""No heartbeat for this long is a gap in telemetry (§6.12: missed heartbeats raise it)."""
OBSERVE_SECONDS = 5
"""A channel the server sees go down must stay down this long before it is an event, so a
reconnecting network or a track republished in a moment raises nothing."""
BATCH_MAX_EVENTS = 100

# The candidate nudge each event can trigger (`hv.state`'s `notice.kind`); the AI also reminds
# the candidate of a CRITICAL one at the next turn.
DEFAULT_NUDGES: dict[str, str] = {
    "FACE_ABSENT": "face_missing",
    "MULTIPLE_FACES": "multiple_faces",
    "UNEXPECTED_PERSON_DETECTED": "multiple_faces",
    "CAMERA_OBSTRUCTED": "camera_covered",
    "PHONE_DETECTED": "phone_detected",
    "APPLICATION_FOCUS_CHANGE": "focus_lost",
    "WINDOW_MINIMIZED": "focus_lost",
    "UNEXPECTED_WINDOW": "focus_lost",
    "BLOCKED_PROCESS_DETECTED": "blocked_application",
    "EXTERNAL_DISPLAY_CHANGE": "second_display",
    "SCREEN_CAPTURE_STOPPED": "screen_share_stopped",
    "CAMERA_DISCONNECTED": "device_disconnected",
    "MIC_DISCONNECTED": "device_disconnected",
    "THIRD_EYE_DISCONNECTED": "third_eye_disconnected",
}
DEFAULT_NUDGE_SETTINGS: dict[str, Any] = {
    "enabled": True,
    "min_severity": "WARNING",
    "cooldown_seconds": 60,
    "max_per_interview": 6,
    "events": DEFAULT_NUDGES,
}
# Tools a candidate who needs them may run (the `assistive_technology` accommodation).
ASSISTIVE_RULES: list[dict[str, Any]] = [
    {"match": "path", "value": "C:\\Windows\\System32\\Narrator.exe"},
    {"match": "path", "value": "C:\\Windows\\System32\\Magnify.exe"},
    {"match": "path", "value": "C:\\Windows\\System32\\osk.exe"},
    {"match": "name", "value": "nvda.exe"},
    {"match": "publisher", "value": "Freedom Scientific"},
    {"match": "publisher", "value": "NV Access"},
]


def _merge(base: dict[str, Any], extra: Mapping[str, Any] | None) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def base_policy(
    level: str,
    *,
    third_eye: str = "optional",
    single_display: bool | None = None,
    categories: Mapping[str, Mapping[str, Any]] | None = None,
    accommodations: Sequence[str] = (),
    overrides: Mapping[str, Any] | None = None,
    blocked: Sequence[Mapping[str, Any]] = (),
    allowed: Sequence[Mapping[str, Any]] = (),
    recording: Mapping[str, bool] | None = None,
) -> dict[str, Any]:
    """The pinned policy for `level`, without the database: defaults, then the level's checks,
    the accommodations, and last the organisation's `overrides` (SP-22's policy editor)."""
    if level not in PROCTORING_PRESETS:
        raise ValueError(f"unknown proctoring level: {level!r}")
    tiers: dict[str, dict[str, int | None]] = {
        event: {"warn_after_ms": warn, "critical_after_ms": critical}
        for event, (warn, critical) in DEFAULT_TIERS.items()
    }
    fixed = dict(DEFAULT_FIXED)
    waived = "third_eye_waiver" in accommodations
    if waived:
        third_eye = "not_required"
    if third_eye == "required":
        warn, critical = REQUIRED_THIRD_EYE_TIER
        tiers["THIRD_EYE_DISCONNECTED"] = {"warn_after_ms": warn, "critical_after_ms": critical}
    elif third_eye == "not_required":
        tiers.pop("THIRD_EYE_DISCONNECTED")
        fixed["THIRD_EYE_DISCONNECTED"] = "INFO"
    if "relaxed_gaze" in accommodations:
        tiers.pop("GAZE_DEVIATION")
        fixed["GAZE_DEVIATION"] = "INFO"
    if "text_answers" in accommodations:
        tiers.pop("MIC_DISCONNECTED")
        fixed["MIC_DISCONNECTED"] = "INFO"
    allow_rules = [dict(rule) for rule in allowed]
    if "assistive_technology" in accommodations:
        allow_rules += copy.deepcopy(ASSISTIVE_RULES)

    policy: dict[str, Any] = {
        "policy_version": PROCTOR_POLICY_VERSION,
        "level": level,
        "checks": list(PROCTORING_PRESETS[level]),
        "third_eye": third_eye,
        "single_display": level == "strict" if single_display is None else single_display,
        "tiers": tiers,
        "fixed": fixed,
        "categories": {key: dict(value) for key, value in (categories or {}).items()},
        "escalation": copy.deepcopy(DEFAULT_ESCALATION),
        "gaze": dict(DEFAULT_GAZE),
        "nudges": copy.deepcopy(DEFAULT_NUDGE_SETTINGS),
        "app_rules": {"blocked": [dict(rule) for rule in blocked], "allowed": allow_rules},
        "heartbeat_seconds": HEARTBEAT_SECONDS,
        "heartbeat_grace_seconds": HEARTBEAT_GRACE_SECONDS,
        "observe_seconds": OBSERVE_SECONDS,
        "batch_max_events": BATCH_MAX_EVENTS,
        "accommodations": sorted(accommodations),
        "recording": dict(recording or {}),
    }
    extra = dict(overrides or {})
    # An override of an event's tiers replaces its fixed severity, and the other way round.
    for event in extra.get("tiers") or {}:
        policy["fixed"].pop(event, None)
    for event in extra.get("fixed") or {}:
        policy["tiers"].pop(event, None)
    return _merge(policy, extra)


def _rule_body(rule: AppRule) -> dict[str, Any]:
    body: dict[str, Any] = {"match": rule.match, "value": rule.value}
    if rule.action == "block":
        body["category"] = rule.category_key
    if rule.conditions:
        body["with"] = [dict(item) for item in rule.conditions]
    return body


async def build_policy(session: AsyncSession, interview: Interview) -> dict[str, Any]:
    """The policy for `interview` as of now; the caller stores it with the proctor session."""
    snapshot = dict(interview.policy or {})
    level = str(snapshot.get("proctoring_level") or "standard")
    if level not in PROCTORING_PRESETS:
        level = "standard"
    categories = {
        row.key: {"severity": row.severity}
        for row in (await session.scalars(select(AppCategory))).all()
    }
    rules = (
        await session.scalars(
            select(AppRule)
            .where(
                AppRule.enabled.is_(True),
                or_(
                    AppRule.organization_id.is_(None),
                    AppRule.organization_id == interview.organization_id,
                ),
            )
            .order_by(AppRule.created_at, AppRule.id)
        )
    ).all()
    overrides = snapshot.get("proctoring")
    return base_policy(
        level,
        third_eye=str(snapshot.get("third_eye") or "optional"),
        categories=categories,
        accommodations=[str(item) for item in snapshot.get("accommodations") or []],
        overrides=overrides if isinstance(overrides, Mapping) else None,
        blocked=[_rule_body(rule) for rule in rules if rule.action == "block"],
        allowed=[_rule_body(rule) for rule in rules if rule.action == "allow"],
        recording=snapshot.get("recording") or None,
    )


def session_view(policy: Mapping[str, Any]) -> dict[str, Any]:
    """The parts of the pinned policy that `POST /proctoring/session` tells the desktop."""
    thresholds = {
        event: {
            "warn_after_ms": tier.get("warn_after_ms"),
            "critical_after_ms": tier.get("critical_after_ms"),
        }
        for event, tier in (policy.get("tiers") or {}).items()
    }
    return {
        "policy_version": policy["policy_version"],
        "level": policy["level"],
        "checks": list(policy["checks"]),
        "thresholds": thresholds,
        "app_rules": copy.deepcopy(policy["app_rules"]),
        "single_display": bool(policy["single_display"]),
        "heartbeat_seconds": int(policy["heartbeat_seconds"]),
        "batch_max_events": int(policy["batch_max_events"]),
        "accommodations": list(policy["accommodations"]),
    }
