"""The `evaluation` stream's consumer (ADR-0015's delivery rules, ADR-0031).

`lifecycle.transition` queues `{"action": "evaluate"}` in the transaction that completes an
interview; an admin's request for a retry or a pinned re-run queues the same event with
`{"action": "evaluate"}` or `{"action": "rerun"}` (`request_evaluation`). The consumer evaluates
with the strong model; after its last attempt `give_up_evaluation` returns the interview to
`completed`, where an admin can ask again.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.ai import AiServices
from hirevion_core.db.session import Database
from hirevion_core.evaluation.compare import Tolerance
from hirevion_core.evaluation.service import BY, evaluate_interview, rerun_pinned
from hirevion_core.interviews.lifecycle import EVALUATION_TOPIC, transition
from hirevion_core.models import Evaluation, Interview
from hirevion_core.outbox import publish_event

log = logging.getLogger(__name__)

__all__ = [
    "EVALUATION_TOPIC",
    "give_up_evaluation",
    "handle_evaluation_event",
    "request_evaluation",
]


async def request_evaluation(
    session: AsyncSession,
    organization_id: UUID,
    interview_id: UUID,
    *,
    action: str = "evaluate",
    requested_by: UUID | None = None,
) -> None:
    """Queues an evaluation (`evaluate`: first or retried) or a pinned re-run (`rerun`)."""
    payload: dict[str, Any] = {"action": action, "interview_id": str(interview_id)}
    if requested_by is not None:
        payload["requested_by"] = str(requested_by)
    await publish_event(session, organization_id, EVALUATION_TOPIC, payload, key=str(interview_id))


async def handle_evaluation_event(
    db: Database, ai: AiServices, organization_id: UUID, payload: dict[str, Any]
) -> None:
    interview_id = UUID(str(payload["interview_id"]))
    action = payload.get("action")
    if action == "evaluate":
        await evaluate_interview(db, ai.llm, organization_id, interview_id)
    elif action == "rerun":
        requested = payload.get("requested_by")
        await rerun_pinned(
            db,
            ai.llm,
            organization_id,
            interview_id,
            UUID(str(requested)) if requested else None,
            Tolerance(),
        )
    else:
        log.warning("Ignoring an evaluation event with action %r", action)


async def give_up_evaluation(db: Database, organization_id: UUID, payload: dict[str, Any]) -> None:
    """Called after the last attempt: whatever is still running is failed, and an interview
    that was being evaluated goes back to `completed`."""
    interview_id = UUID(str(payload["interview_id"]))
    async with db.tenant(organization_id) as session:
        interview = await session.get(Interview, interview_id, with_for_update=True)
        if interview is None:
            return
        running = (
            await session.scalars(
                select(Evaluation).where(
                    Evaluation.interview_id == interview_id, Evaluation.status == "running"
                )
            )
        ).all()
        for evaluation in running:
            evaluation.status, evaluation.error = "failed", "gave_up"
        if payload.get("action") == "evaluate" and interview.status == "evaluating":
            await transition(
                session,
                interview,
                "completed",
                "evaluation_failed",
                BY,
                reason="The evaluation could not be completed; ask for it again.",
            )
