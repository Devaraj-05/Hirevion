"""The interview lifecycle (master plan §7): Scheduled → Invited → In Progress ⇄ Interrupted →
Completed → Evaluating → Evaluated, or Expired, Cancelled, Abandoned.

Every change goes through `transition()`: it checks the move against `TRANSITIONS`, sets the
status and its timestamp, writes an `interview_events` row and an audit entry, and queues the
domain events SP-18's webhooks send (`interview.created`, `interview.started`,
`interview.completed`, `interview.abandoned`). Rescheduling an invited interview is the move
`invited → invited`; re-running an evaluation moves `evaluated → evaluating`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.actor import Actor
from hirevion_core.access.errors import Conflict
from hirevion_core.audit import AuditEntry, AuditService
from hirevion_core.models import Interview, InterviewEvent
from hirevion_core.outbox import publish_event

TRANSITIONS: dict[str, frozenset[str]] = {
    "scheduled": frozenset({"invited", "cancelled", "expired"}),
    "invited": frozenset({"invited", "in_progress", "cancelled", "expired"}),
    "in_progress": frozenset({"interrupted", "completed", "abandoned"}),
    "interrupted": frozenset({"in_progress", "completed", "abandoned"}),
    "completed": frozenset({"evaluating"}),
    "evaluating": frozenset({"evaluated", "completed"}),
    "evaluated": frozenset({"evaluating"}),
    "expired": frozenset({"invited"}),
    "cancelled": frozenset(),
    "abandoned": frozenset(),
}
# Interviews still to happen, happening, and over, for the /interviews tabs (PRD §7).
STATUS_GROUPS: dict[str, tuple[str, ...]] = {
    "upcoming": ("scheduled", "invited"),
    "live": ("in_progress", "interrupted"),
    "completed": (
        "completed",
        "evaluating",
        "evaluated",
        "expired",
        "cancelled",
        "abandoned",
    ),
}
# Domain events for SP-18's webhooks (PRD §77), queued when an interview reaches a status.
WEBHOOK_TOPICS = {
    "in_progress": "interview.started",
    "completed": "interview.completed",
    # SP-09: an interview left interrupted past its grace still gets its transcript written.
    "abandoned": "interview.abandoned",
}

# SP-10: the internal stream its evaluator consumes. A completed interview queues an event here
# (rather than sharing `interview.completed`'s stream, whose consumers delete what they finish).
EVALUATION_TOPIC = "evaluation"

ActorType = Literal["user", "candidate", "system", "agent"]
_audit = AuditService()


@dataclass(frozen=True, slots=True)
class By:
    """Who made a change: a recruiter (`Actor`), the candidate, the system or the AI agent."""

    type: ActorType
    id: str | None = None
    ip: str | None = None
    user_agent: str | None = None

    @classmethod
    def user(cls, actor: Actor) -> By:
        return cls("user", str(actor.user_id), actor.ip, actor.user_agent)

    @classmethod
    def system(cls) -> By:
        return cls("system", "scheduler")


def can_transition(source: str, target: str) -> bool:
    return target in TRANSITIONS.get(source, frozenset())


def require_transition(source: str, target: str) -> None:
    if not can_transition(source, target):
        raise Conflict(
            "invalid-transition",
            f"An interview can't go from {source} to {target}",
            field="status",
        )


def _now() -> datetime:
    return datetime.now(UTC)


async def record_event(
    session: AsyncSession,
    interview: Interview,
    action: str,
    by: By,
    *,
    from_status: str | None,
    reason: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> None:
    """An event in the interview's history and the organisation's audit chain."""
    session.add(
        InterviewEvent(
            organization_id=interview.organization_id,
            interview_id=interview.id,
            from_status=from_status,
            to_status=interview.status,
            action=action,
            reason=reason,
            actor_type=by.type,
            actor_id=by.id,
            details=dict(details or {}),
        )
    )
    await _audit.append(
        session,
        interview.organization_id,
        AuditEntry(
            action=f"interview.{action}",
            resource_type="interview",
            resource_id=str(interview.id),
            actor_type=by.type,
            actor_id=by.id,
            ip=by.ip,
            user_agent=by.user_agent,
            details={
                "from": from_status,
                "to": interview.status,
                **({"reason": reason} if reason else {}),
                **dict(details or {}),
            },
        ),
    )
    await session.flush()


async def transition(
    session: AsyncSession,
    interview: Interview,
    target: str,
    action: str,
    by: By,
    *,
    reason: str | None = None,
    details: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> None:
    """Moves `interview` to `target` (or refuses with a Conflict), recording why."""
    require_transition(interview.status, target)
    source = interview.status
    moment = now or _now()
    interview.status = target
    if target == "invited":
        interview.invited_at = moment
    elif target == "in_progress" and interview.started_at is None:
        interview.started_at = moment
    elif target == "completed" and source != "evaluating":
        interview.completed_at = moment
        interview.ended_at = moment
    elif target in ("expired", "cancelled", "abandoned"):
        interview.ended_at = moment
    await record_event(
        session, interview, action, by, from_status=source, reason=reason, details=details
    )
    topic = WEBHOOK_TOPICS.get(target)
    # A resumed interview (interrupted → in progress) didn't start again, and a re-evaluated one
    # (evaluating → completed) didn't complete again; one completed while interrupted did.
    repeat = (
        source == target
        or source == "evaluating"
        or (target == "in_progress" and source == "interrupted")
    )
    if topic is not None and not repeat:
        await publish_event(
            session,
            interview.organization_id,
            topic,
            interview_payload(interview),
            key=str(interview.id),
        )
    if target == "completed" and not repeat:
        await publish_event(
            session,
            interview.organization_id,
            EVALUATION_TOPIC,
            {"action": "evaluate", "interview_id": str(interview.id)},
            key=str(interview.id),
        )


def interview_payload(interview: Interview) -> dict[str, Any]:
    """What domain events say about an interview: ids and status, never personal details."""
    return {
        "interview_id": str(interview.id),
        "candidate_id": str(interview.candidate_id),
        "job_id": str(interview.job_id),
        "application_id": str(interview.application_id),
        "status": interview.status,
    }


def reference(number: int) -> str:
    """How people see an interview's number: IV-0042."""
    return f"IV-{number:04d}"


__all__ = [
    "EVALUATION_TOPIC",
    "STATUS_GROUPS",
    "TRANSITIONS",
    "By",
    "can_transition",
    "interview_payload",
    "record_event",
    "reference",
    "require_transition",
    "transition",
]
