"""The event normaliser (PRD §54's second stage): what a device reports becomes one stored shape.
Times are clamped, details are cleaned of anything a key typed, and a blocked process is tied to
the rule in the session's pinned policy, so the category the server judges by is the server's,
not the device's claim."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from hirevion_core.proctoring.catalogue import (
    CLIENT_EVENTS,
    PHASES,
    RANK,
    SOURCES,
    clean_details,
)

MAX_DURATION_MS = 6 * 3600 * 1000
FUTURE_SLACK = timedelta(minutes=5)
MAX_EVIDENCE = 10


class UnknownEvent(ValueError):
    """An event or source name the contract doesn't list: the whole batch is refused."""


@dataclass(frozen=True, slots=True)
class Incoming:
    """One event as the device sent it, after the schema's own checks."""

    seq: int
    event: str
    source: str
    started_at: datetime
    duration_ms: int | None = None
    confidence: float | None = None
    evidence: list[dict[str, str]] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Normalised:
    seq: int
    event: str
    source: str
    started_at: datetime
    duration_ms: int | None
    confidence: float | None
    phase: str | None
    ongoing: bool
    details: dict[str, Any]
    evidence: list[dict[str, str]]
    category: str | None
    hint: str | None


def check_names(items: list[Incoming]) -> None:
    """Refuses a batch with an event or source the contract doesn't know (`422 unknown-event`)."""
    for item in items:
        if item.event not in CLIENT_EVENTS:
            raise UnknownEvent(f"unknown event {item.event[:60]!r}")
        if item.source not in SOURCES:
            raise UnknownEvent(f"unknown source {item.source[:60]!r}")


def _category(event: str, details: Mapping[str, Any], policy: Mapping[str, Any]) -> str | None:
    if event != "BLOCKED_PROCESS_DETECTED":
        return None
    blocked = (policy.get("app_rules") or {}).get("blocked") or []
    index = details.get("rule_index")
    if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(blocked):
        category = blocked[index].get("category")
        if category:
            return str(category)
    claimed = details.get("category")
    if isinstance(claimed, str) and claimed in (policy.get("categories") or {}):
        return claimed
    return None


def normalise(item: Incoming, policy: Mapping[str, Any], *, now: datetime) -> Normalised:
    started = item.started_at if item.started_at.tzinfo else item.started_at.replace(tzinfo=UTC)
    details = clean_details(item.details)
    if started > now + FUTURE_SLACK:
        details["clock_skew_ms"] = int((started - now).total_seconds() * 1000)
        started = now
    duration = None if item.duration_ms is None else min(max(item.duration_ms, 0), MAX_DURATION_MS)
    confidence = None if item.confidence is None else min(max(float(item.confidence), 0.0), 1.0)
    phase = details.get("phase")
    phase = phase if phase in PHASES else None
    hint = details.get("severity_hint")
    hint = hint.upper() if isinstance(hint, str) and hint.upper() in RANK else None
    evidence = [
        {"type": str(entry["type"])[:40], "blob_path": str(entry["blob_path"])[:400]}
        for entry in item.evidence[:MAX_EVIDENCE]
        if entry.get("type") and entry.get("blob_path")
    ]
    return Normalised(
        seq=item.seq,
        event=item.event,
        source=item.source,
        started_at=started,
        duration_ms=duration,
        confidence=confidence,
        phase=phase,
        ongoing=details.get("ongoing") is True or phase in ("started", "escalated"),
        details=details,
        evidence=evidence,
        category=_category(item.event, details, policy),
        hint=hint,
    )
