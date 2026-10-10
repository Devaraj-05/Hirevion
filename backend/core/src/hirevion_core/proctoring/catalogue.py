"""What the proctoring engine knows about events (PRD §55, §60 to §63, master plan §6.12): their
names, where they come from, which policy check switches them on, and how to clean the free-form
`details` a device sends. The desktop's `docs/api/contracts/proctoring.md` lists the same names."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

SEVERITIES = ("INFO", "WARNING", "CRITICAL")
RANK = {name: index for index, name in enumerate(SEVERITIES)}
SOURCES = ("camera", "third_eye", "screen", "native", "editor", "audio", "interview")
PHASES = ("started", "escalated", "ended")
PHASE_RANK = {name: index for index, name in enumerate(PHASES)}
REVIEW_OUTCOMES = ("confirmed", "false_positive", "not_relevant")
REVIEW_STATUSES = ("pending", *REVIEW_OUTCOMES)
# §67's seven kinds of evidence.
EVIDENCE_KINDS = (
    "screenshot",
    "video_segment",
    "camera_segment",
    "third_eye_segment",
    "screen_segment",
    "transcript_segment",
    "process_metadata",
)
# The checks a proctoring level can switch on (templates.PROCTORING_PRESETS).
CHECKS = ("face", "focus", "gaze", "phone", "processes", "displays", "audio", "third_eye")


@dataclass(frozen=True, slots=True)
class EventKind:
    name: str
    source: str
    """Where it usually comes from; a device may report another source."""
    check: str | None = None
    """The policy check that switches it on; None for what always runs because it protects the
    interview itself (devices, the environment, the session's own lifecycle)."""
    client: bool = True
    """False for events only the server raises."""


def _kinds(*items: EventKind) -> dict[str, EventKind]:
    return {item.name: item for item in items}


EVENTS: dict[str, EventKind] = _kinds(
    # Camera.
    EventKind("FACE_ABSENT", "camera", "face"),
    EventKind("MULTIPLE_FACES", "camera", "face"),
    EventKind("FACE_TOO_FAR", "camera", "face"),
    EventKind("FACE_TOO_CLOSE", "camera", "face"),
    EventKind("GAZE_DEVIATION", "camera", "gaze"),
    EventKind("CAMERA_OBSTRUCTED", "camera", "face"),
    EventKind("PHONE_DETECTED", "camera", "phone"),
    EventKind("UNEXPECTED_PERSON_DETECTED", "camera", "face"),
    # Devices.
    EventKind("CAMERA_DISCONNECTED", "camera"),
    EventKind("MIC_DISCONNECTED", "audio"),
    EventKind("SCREEN_CAPTURE_STOPPED", "screen"),
    EventKind("DEVICE_CHANGE", "native"),
    # Focus and processes.
    EventKind("APPLICATION_FOCUS_CHANGE", "native", "focus"),
    EventKind("WINDOW_MINIMIZED", "native", "focus"),
    EventKind("UNEXPECTED_WINDOW", "native", "focus"),
    EventKind("BLOCKED_PROCESS_DETECTED", "native", "processes"),
    EventKind("EXTERNAL_DISPLAY_CHANGE", "native", "displays"),
    # The environment.
    EventKind("CAPTURE_EXCLUDED_WINDOW", "native"),
    EventKind("REMOTE_SESSION_DETECTED", "native"),
    EventKind("VIRTUAL_DEVICE_DETECTED", "native"),
    EventKind("VM_DETECTED", "native"),
    EventKind("CLIENT_INTEGRITY_WARNING", "native"),
    # Audio.
    EventKind("ADDITIONAL_SPEAKER_DETECTED", "audio", "audio"),
    # Lifecycle.
    EventKind("CAMERA_RECONNECTED", "camera"),
    EventKind("MIC_RECONNECTED", "audio"),
    EventKind("SESSION_INTERRUPTED", "interview"),
    EventKind("SESSION_RESUMED", "interview"),
    # The coding editor.
    EventKind("EDITOR_PASTE", "editor"),
    EventKind("EDITOR_FOCUS_CHANGE", "editor"),
    # Only the server raises these (from LiveKit, heartbeats and upload continuity).
    EventKind("THIRD_EYE_DISCONNECTED", "third_eye", client=False),
    EventKind("THIRD_EYE_RECONNECTED", "third_eye", client=False),
    EventKind("TELEMETRY_GAP", "interview", client=False),
)
CLIENT_EVENTS = frozenset(name for name, kind in EVENTS.items() if kind.client)

# Keys that could carry what a key typed or what was copied: never stored (PRD §60 forbids key
# logging). The desktop never sends them; this keeps a faulty or hostile client from filling the
# report with them.
FORBIDDEN_KEYS = frozenset(
    {
        "key",
        "keys",
        "keycode",
        "keycodes",
        "key_codes",
        "keystroke",
        "keystrokes",
        "typed",
        "typed_text",
        "text",
        "input",
        "clipboard",
        "content",
        "pasted",
        "pasted_text",
    }
)
MAX_STRING = 300
MAX_DEPTH = 4
MAX_ITEMS = 40
MAX_DETAILS_BYTES = 8192


def _clean(value: Any, depth: int) -> Any:
    if isinstance(value, str):
        return value[:MAX_STRING]
    if isinstance(value, bool) or value is None or isinstance(value, int | float):
        return value
    if depth >= MAX_DEPTH:
        return None
    if isinstance(value, Mapping):
        return {
            str(key)[:60]: _clean(item, depth + 1)
            for key, item in list(value.items())[:MAX_ITEMS]
            if str(key).lower() not in FORBIDDEN_KEYS
        }
    if isinstance(value, list | tuple):
        return [_clean(item, depth + 1) for item in value[:MAX_ITEMS]]
    return None


def clean_details(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """The device's details without forbidden keys, bounded in depth, length and size."""
    cleaned = _clean(dict(raw or {}), 0)
    if not isinstance(cleaned, dict):
        return {}
    while len(json.dumps(cleaned, ensure_ascii=False)) > MAX_DETAILS_BYTES and cleaned:
        biggest = max(cleaned, key=lambda key: len(json.dumps(cleaned[key], ensure_ascii=False)))
        del cleaned[biggest]
        cleaned["truncated"] = True
    return cleaned


def check_enabled(event: str, checks: list[str] | tuple[str, ...]) -> bool:
    """Whether the policy's checks cover the event (always-on events are covered)."""
    kind = EVENTS.get(event)
    return kind is None or kind.check is None or kind.check in checks
