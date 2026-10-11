"""A recruiter's review of a proctoring event (master plan §6.12; the §106 false-positive KPI).

An event is confirmed, marked a false positive, or marked not relevant, always with a reason, and
every decision is audited with the one before it. Nothing is deleted or hidden: a dismissed event
stays in the report, marked as dismissed, so the report shows what the system saw and what a
person made of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access import audit
from hirevion_core.access.actor import Actor
from hirevion_core.access.errors import Invalid, NotFound
from hirevion_core.interview_session import realtime
from hirevion_core.models import ProctorEvent, ProctorEventReview
from hirevion_core.proctoring.catalogue import REVIEW_OUTCOMES

MAX_REASON = 1000


@dataclass(frozen=True, slots=True)
class Reviewed:
    event: ProctorEvent
    review: ProctorEventReview


async def review_event(
    session: AsyncSession,
    actor: Actor,
    interview_id: UUID,
    event_id: UUID,
    outcome: str,
    reason: str,
) -> Reviewed:
    if outcome not in REVIEW_OUTCOMES:
        raise Invalid("invalid-outcome", "Choose confirmed, false positive or not relevant")
    reason = reason.strip()
    if not reason or len(reason) > MAX_REASON:
        raise Invalid("reason-required", "Give a reason of up to 1000 characters", field="reason")
    event = await session.scalar(
        select(ProctorEvent)
        .where(ProctorEvent.id == event_id, ProctorEvent.interview_id == interview_id)
        .with_for_update()
    )
    if event is None:
        raise NotFound("event-not-found", "No such proctoring event")
    previous = event.review_status
    event.review_status = outcome
    review = ProctorEventReview(
        organization_id=event.organization_id,
        proctor_event_id=event.id,
        interview_id=interview_id,
        reviewer_id=actor.user_id,
        outcome=outcome,
        previous=previous,
        reason=reason,
    )
    session.add(review)
    await session.flush()
    await audit.record(
        session,
        actor,
        "proctoring.event_reviewed",
        "proctor_event",
        event.id,
        details={
            "interview_id": str(interview_id),
            "event": event.event,
            "severity": event.severity,
            "outcome": outcome,
            "previous": previous,
            "reason": reason,
        },
    )
    return Reviewed(event, review)


async def publish_review(redis: Redis, interview_id: UUID, done: Reviewed) -> None:
    await realtime.publish(
        redis,
        interview_id,
        "PROCTOR_REVIEW",
        {
            "event_id": str(done.event.id),
            "review_status": done.event.review_status,
            "reviewer_id": str(done.review.reviewer_id),
            "reason": done.review.reason,
        },
    )
