"""The recruiter's live view of an interview (PRD §65, §66): one snapshot to start from, then the
stream. The snapshot holds the devices and connection health, the AI's state, the transcript's
tail, the recent events, the counts, and `cursor`, the stream position the snapshot is current
to: following the stream from it misses nothing and repeats nothing."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.interview_session import realtime
from hirevion_core.interview_session.conductor import agent_key, hot_key
from hirevion_core.models import (
    Interview,
    InterviewSession,
    ProctorEvent,
    ProctorSession,
    TranscriptSegment,
)
from hirevion_core.proctoring.store import event_json, status_json

RECENT_EVENTS = 30
TRANSCRIPT_TAIL = 8


async def counts(session: AsyncSession, interview_id: UUID) -> dict[str, Any]:
    rows = await session.execute(
        select(ProctorEvent.severity, ProctorEvent.review_status, func.count())
        .where(ProctorEvent.interview_id == interview_id)
        .group_by(ProctorEvent.severity, ProctorEvent.review_status)
    )
    by_severity = {"INFO": 0, "WARNING": 0, "CRITICAL": 0}
    by_review = {"pending": 0, "confirmed": 0, "false_positive": 0, "not_relevant": 0}
    open_alerts = 0
    for severity, review, number in rows:
        by_severity[severity] += number
        by_review[review] += number
        if severity != "INFO" and review == "pending":
            open_alerts += number
    return {
        "total": sum(by_severity.values()),
        "by_severity": by_severity,
        "by_review": by_review,
        "dismissed": by_review["false_positive"] + by_review["not_relevant"],
        "open_alerts": open_alerts,
    }


async def snapshot(session: AsyncSession, redis: Redis, interview: Interview) -> dict[str, Any]:
    # The cursor first: events published while the rest is read are then replayed, and the
    # dashboard merges by id.
    cursor = await realtime.last_id(redis, interview.id)
    proctor = await session.scalar(
        select(ProctorSession).where(ProctorSession.interview_id == interview.id)
    )
    recent = (
        await session.scalars(
            select(ProctorEvent)
            .where(ProctorEvent.interview_id == interview.id)
            .order_by(ProctorEvent.started_at.desc(), ProctorEvent.id.desc())
            .limit(RECENT_EVENTS)
        )
    ).all()
    tail = (
        await session.scalars(
            select(TranscriptSegment)
            .where(TranscriptSegment.interview_id == interview.id)
            .order_by(TranscriptSegment.seq.desc())
            .limit(TRANSCRIPT_TAIL)
        )
    ).all()
    run = await session.get(InterviewSession, interview.id)
    hot: dict[Any, Any] = await redis.hgetall(hot_key(interview.id))
    voice = hot.get(b"voice") or hot.get("voice")
    return {
        "interview": {
            "status": interview.status,
            "started_at": interview.started_at.isoformat() if interview.started_at else None,
            "deadline_at": run.deadline_at.isoformat() if run is not None else None,
            "duration_minutes": interview.duration_minutes,
        },
        "proctoring": status_json(proctor, interview.status) if proctor is not None else None,
        "ai": {
            "voice": voice.decode() if isinstance(voice, bytes) else voice,
            "agent_connected": bool(await redis.exists(agent_key(interview.id))),
        },
        "counts": await counts(session, interview.id),
        "events": [event_json(row) for row in recent],
        "transcript": [
            {"seq": row.seq, "speaker": row.speaker, "text": row.text, "start_ms": row.start_ms}
            for row in reversed(tail)
        ],
        "cursor": cursor,
    }
