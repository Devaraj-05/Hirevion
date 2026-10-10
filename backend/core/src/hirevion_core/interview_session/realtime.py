"""PRD §91's live events for one interview, on a capped Valkey stream per interview
(`hv:rt:interview:{id}`). A reader replays from the last id it saw and then follows, so a
reconnecting dashboard misses nothing still on the stream.

SP-09 publishes `AI_SPEAKING`, `CANDIDATE_SPEAKING`, `QUESTION_STARTED`, `ANSWER_RECEIVED` and
`INTERVIEW_COMPLETED`; SP-12, SP-13, SP-14 and SP-16 add `RECORDING_STATUS`, `THIRD_EYE_STATUS`,
`PROCTOR_EVENT`, `CODE_RUN` and `CODE_SUBMITTED` to the same stream (SP-14 also sends
`PROCTOR_STATUS`, the devices and connection health, and `PROCTOR_REVIEW`; the proctoring types go
only to readers with `reports.proctoring.view`). Events carry ids, timing and
what was said, never a score.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from redis.asyncio import Redis

EventType = Literal[
    "AI_SPEAKING",
    "CANDIDATE_SPEAKING",
    "QUESTION_STARTED",
    "ANSWER_RECEIVED",
    "PROCTOR_EVENT",
    "PROCTOR_STATUS",
    "PROCTOR_REVIEW",
    "CODE_RUN",
    "CODE_SUBMITTED",
    "RECORDING_STATUS",
    "THIRD_EYE_STATUS",
    "INTERVIEW_COMPLETED",
]
EVENT_TYPES: tuple[str, ...] = (
    "AI_SPEAKING",
    "CANDIDATE_SPEAKING",
    "QUESTION_STARTED",
    "ANSWER_RECEIVED",
    "PROCTOR_EVENT",
    "PROCTOR_STATUS",
    "PROCTOR_REVIEW",
    "CODE_RUN",
    "CODE_SUBMITTED",
    "RECORDING_STATUS",
    "THIRD_EYE_STATUS",
    "INTERVIEW_COMPLETED",
)
# What only readers of the proctoring report may see.
PROCTORING_TYPES = frozenset({"PROCTOR_EVENT", "PROCTOR_STATUS", "PROCTOR_REVIEW"})
STREAM_MAX = 2000
STREAM_TTL_SECONDS = 2 * 24 * 3600


def stream_key(interview_id: UUID) -> str:
    return f"hv:rt:interview:{interview_id}"


@dataclass(frozen=True, slots=True)
class LiveEvent:
    id: str
    type: str
    interview_id: str
    at: str
    data: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "interview_id": self.interview_id,
            "at": self.at,
            "data": self.data,
        }


async def publish(
    redis: Redis,
    interview_id: UUID,
    type: EventType,
    data: dict[str, Any],
    *,
    at: datetime | None = None,
) -> str:
    key = stream_key(interview_id)
    body = json.dumps(
        {
            "type": type,
            "interview_id": str(interview_id),
            "at": (at or datetime.now(UTC)).isoformat(),
            "data": data,
        },
        ensure_ascii=False,
    )
    event_id = await redis.xadd(key, {"event": body}, maxlen=STREAM_MAX, approximate=True)
    await redis.expire(key, STREAM_TTL_SECONDS)
    return event_id.decode() if isinstance(event_id, bytes) else str(event_id)


def _decode(event_id: Any, fields: dict[Any, Any]) -> LiveEvent:
    raw = fields.get(b"event") or fields.get("event") or b"{}"
    body = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
    return LiveEvent(
        id=event_id.decode() if isinstance(event_id, bytes) else str(event_id),
        type=str(body.get("type")),
        interview_id=str(body.get("interview_id")),
        at=str(body.get("at")),
        data=dict(body.get("data") or {}),
    )


async def read(
    redis: Redis,
    interview_id: UUID,
    after: str = "0",
    *,
    block_ms: int | None = None,
    count: int = 200,
) -> list[LiveEvent]:
    """Events after `after` ("0" from the start, "$" only new ones), waiting up to `block_ms`."""
    answer: Any = await redis.xread({stream_key(interview_id): after}, count=count, block=block_ms)
    events: list[LiveEvent] = []
    for _, entries in answer or []:
        events += [_decode(event_id, fields) for event_id, fields in entries]
    return events


async def last_id(redis: Redis, interview_id: UUID) -> str:
    """The newest event's id ("0-0" when there's none): where "only new events" starts, so
    nothing published between two reads is missed."""
    newest: Any = await redis.xrevrange(stream_key(interview_id), count=1)
    if not newest:
        return "0-0"
    event_id = newest[0][0]
    return event_id.decode() if isinstance(event_id, bytes) else str(event_id)
