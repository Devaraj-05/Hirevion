"""Recruiter actions on applications (PRD §18): shortlist, reject, hold, review, and assigning a
recruiter or hiring manager, singly or in bulk. Every change is kept in `application_history`
and the audit log. Going against the AI's ordering (shortlisting from the bottom half, rejecting
from the top quarter) is an override: it needs a reason and is marked as one."""

from __future__ import annotations

import math
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.actor import Actor
from hirevion_core.access.audit import record
from hirevion_core.access.errors import Conflict, Invalid, NotFound
from hirevion_core.hiring.workflow import change_status, finished_interview
from hirevion_core.models import Application, ScreeningResult, User
from hirevion_core.screening.engine import record_stage

STAGE_ACTIONS = {
    "shortlist": ("shortlisted", "application.shortlisted"),
    "reject": ("rejected", "application.rejected"),
    "hold": ("on_hold", "application.held"),
    "review": ("review", "application.reviewed"),
}
ASSIGN_ACTIONS = {
    "assign_recruiter": "recruiter_id",
    "assign_hiring_manager": "hiring_manager_id",
}
ACTIONS = tuple(STAGE_ACTIONS) + tuple(ASSIGN_ACTIONS)
MAX_BULK = 500
REASON_MAX = 1000


def _is_override(action: str, rank: int | None, ranked: int) -> bool:
    if rank is None or ranked == 0:
        return False
    if action == "shortlist":
        return rank > math.ceil(ranked / 2)
    if action == "reject":
        return rank <= max(1, math.ceil(ranked / 4))
    return False


async def act(
    session: AsyncSession,
    actor: Actor,
    job_id: UUID,
    application_ids: Sequence[UUID],
    action: str,
    *,
    reason: str | None = None,
    user_id: UUID | None = None,
) -> list[Application]:
    if action not in ACTIONS:
        raise Invalid("unknown-action", "Unknown action", field="action")
    ids = list(dict.fromkeys(application_ids))
    if not ids or len(ids) > MAX_BULK:
        raise Invalid(
            "invalid-selection", f"Choose 1 to {MAX_BULK} candidates", field="application_ids"
        )
    reason = (reason or "").strip()[:REASON_MAX] or None
    applications = list(
        (
            await session.scalars(
                select(Application).where(Application.id.in_(ids), Application.job_id == job_id)
            )
        ).all()
    )
    if len(applications) != len(ids):
        raise NotFound("application-not-found", "No such application for this job")

    if action in ASSIGN_ACTIONS:
        return await _assign(session, actor, job_id, applications, action, user_id)

    target, audit_action = STAGE_ACTIONS[action]
    ranked = int(
        await session.scalar(
            select(func.count())
            .select_from(Application)
            .where(Application.job_id == job_id, Application.rank.is_not(None))
        )
        or 0
    )
    overrides = {app.id: _is_override(action, app.rank, ranked) for app in applications}
    if not reason and (action == "reject" or any(overrides.values())):
        raise Invalid(
            "reason-required",
            "Say why: a rejection, or a decision against the ranking, needs a reason",
            field="reason",
        )
    scores = {
        row[0]: row[1]
        for row in await session.execute(
            select(ScreeningResult.id, ScreeningResult.score).where(
                ScreeningResult.id.in_(
                    [app.screening_result_id for app in applications if app.screening_result_id]
                )
            )
        )
    }
    for application in applications:
        if application.stage == target or application.stage == "uploaded":
            continue
        if application.hiring_status == "selected":
            raise Conflict(
                "application-selected",
                "A candidate was selected for this job: change the hiring status to reopen it",
            )
        if action == "reject" and await finished_interview(session, application.id) is not None:
            # After an interview a rejection is the final decision (PRD §72): it needs the
            # permission to decide and is recorded as one.
            await change_status(session, actor, application.id, "rejected", reason=reason)
            continue
        previous = application.stage
        score = (
            scores.get(application.screening_result_id) if application.screening_result_id else None
        )
        await record_stage(
            session,
            application,
            target,
            action,
            actor_id=actor.user_id,
            reason=reason,
            score=score,
            rank=application.rank,
            override=overrides[application.id],
        )
        await record(
            session,
            actor,
            audit_action,
            "application",
            application.id,
            details={
                "job_id": str(job_id),
                "candidate_id": str(application.candidate_id),
                "from": previous,
                "to": target,
                "score": score,
                "rank": application.rank,
                "override": overrides[application.id],
                "reason": reason,
            },
        )
    await session.flush()
    return applications


async def _assign(
    session: AsyncSession,
    actor: Actor,
    job_id: UUID,
    applications: list[Application],
    action: str,
    user_id: UUID | None,
) -> list[Application]:
    if user_id is not None:
        user = await session.get(User, user_id)
        if user is None or user.status == "disabled":
            raise Invalid("invalid-user", "Choose someone in this organisation", field="user_id")
    column = ASSIGN_ACTIONS[action]
    for application in applications:
        if getattr(application, column) == user_id:
            continue
        setattr(application, column, user_id)
        await record_stage(session, application, application.stage, action, actor_id=actor.user_id)
        await record(
            session,
            actor,
            "application.assigned",
            "application",
            application.id,
            details={
                "job_id": str(job_id),
                "role": "recruiter" if column == "recruiter_id" else "hiring_manager",
                "user_id": str(user_id) if user_id else None,
            },
        )
    await session.flush()
    return applications
