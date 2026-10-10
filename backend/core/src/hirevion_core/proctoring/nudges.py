"""Candidate nudges (master plan §6.12: "candidate nudges are configurable").

A nudge is a short notice on the candidate's screen ("I can't see you on camera"): the `notice`
of `hv.state` (`docs/api/contracts/interview-session.md`). The policy says which events nudge,
from which severity, how often one kind may repeat and how many a candidate gets. Delivery is
through the interview's hot copy (so `GET /session` carries it, which is how text-mode interviews
get it) and a small stream the interview agent follows to publish `hv.state` at once. The AI also
reminds a candidate of a CRITICAL event at the next turn, through the Conductor.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from redis.asyncio import Redis

from hirevion_core.interview_session.conductor import HOT_TTL_SECONDS, hot_key
from hirevion_core.proctoring.catalogue import RANK

STREAM_MAX = 50
TEXTS = {
    "face_missing": "I can't see you on camera. Please stay in view of the camera.",
    "multiple_faces": "Someone else may be with you. Please continue on your own.",
    "camera_covered": "Your camera appears to be covered. Please make sure your face is visible.",
    "phone_detected": "Please put any phones or other devices away.",
    "focus_lost": "Please keep the interview app in focus.",
    "blocked_application": "Please close the other application that is running.",
    "second_display": "Please use a single display for this interview.",
    "screen_share_stopped": "Your screen is no longer being captured. Please restore it.",
    "device_disconnected": "Your camera or microphone seems disconnected. Please reconnect it.",
    "third_eye_disconnected": "Your phone camera has disconnected. Please reconnect it.",
}


def stream_key(interview_id: UUID) -> str:
    return f"hv:iv:{interview_id}:nudges"


@dataclass(frozen=True, slots=True)
class Nudge:
    id: str
    kind: str
    event: str
    severity: str
    at: str

    def notice(self) -> dict[str, Any]:
        """The `notice` of `hv.state`."""
        return {
            "id": self.id,
            "kind": self.kind,
            "event": self.event,
            "severity": self.severity,
            "text": TEXTS.get(self.kind, "Please keep to the interview's rules."),
            "at": self.at,
        }


def plan(
    policy: Mapping[str, Any],
    state: dict[str, Any],
    *,
    event_id: str,
    event: str,
    severity: str,
    now: datetime,
) -> Nudge | None:
    """The nudge this event earns, or None. `state` is the session's record of what it already
    sent (`{"count": n, "last": {kind: iso}}`) and is updated when a nudge is returned."""
    settings = policy.get("nudges") or {}
    if not settings.get("enabled"):
        return None
    kind = (settings.get("events") or {}).get(event)
    if kind is None or RANK[severity] < RANK.get(str(settings.get("min_severity")), 1):
        return None
    if int(state.get("count", 0)) >= int(settings.get("max_per_interview", 0)):
        return None
    last = (state.get("last") or {}).get(kind)
    cooldown = timedelta(seconds=int(settings.get("cooldown_seconds", 60)))
    if last is not None and now - datetime.fromisoformat(last) < cooldown:
        return None
    state["count"] = int(state.get("count", 0)) + 1
    state.setdefault("last", {})[kind] = now.astimezone(UTC).isoformat()
    return Nudge(event_id, kind, event, severity, now.astimezone(UTC).isoformat())


async def deliver(redis: Redis, interview_id: UUID, nudge: Nudge) -> None:
    """Shows the nudge: the hot copy `GET /session` reads, and the stream the agent follows."""
    body = json.dumps(nudge.notice(), ensure_ascii=False)
    await redis.hset(hot_key(interview_id), mapping={"notice": body})
    await redis.expire(hot_key(interview_id), HOT_TTL_SECONDS)
    await redis.xadd(
        stream_key(interview_id), {"notice": body}, maxlen=STREAM_MAX, approximate=True
    )
    await redis.expire(stream_key(interview_id), HOT_TTL_SECONDS)


async def read(
    redis: Redis, interview_id: UUID, after: str = "$", *, block_ms: int | None = None
) -> list[tuple[str, dict[str, Any]]]:
    """Nudges after `after`, as `(id, notice)`; the agent passes the last id it published."""
    answer: Any = await redis.xread({stream_key(interview_id): after}, count=20, block=block_ms)
    found: list[tuple[str, dict[str, Any]]] = []
    for _, entries in answer or []:
        for entry_id, fields in entries:
            raw = fields.get(b"notice") or fields.get("notice") or b"{}"
            found.append(
                (
                    entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id),
                    json.loads(raw.decode() if isinstance(raw, bytes) else raw),
                )
            )
    return found
