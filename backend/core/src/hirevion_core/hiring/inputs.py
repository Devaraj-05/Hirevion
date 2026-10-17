"""Hiring Manager input (PRD §6): a structured recommendation with a rationale. It informs the
person who makes the decision and never moves the application's status by itself. Each submission
is a new row; the latest one per author is the one that counts."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.actor import Actor
from hirevion_core.access.audit import record
from hirevion_core.access.errors import Invalid
from hirevion_core.hiring.workflow import finished_interview
from hirevion_core.models import Application, HiringInput, Interview
from hirevion_core.models.reporting import RECOMMENDATIONS

RATING_KEYS = ("technical", "communication", "role_fit")
RATIONALE_MAX = 4000


def _ratings(values: Mapping[str, int]) -> dict[str, int]:
    unknown = sorted(set(values) - set(RATING_KEYS))
    if unknown:
        raise Invalid("invalid-ratings", f"Unknown rating: {', '.join(unknown)}", field="ratings")
    for name, value in values.items():
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
            raise Invalid("invalid-ratings", f"Rate {name} from 1 to 5", field="ratings")
    return {name: int(values[name]) for name in RATING_KEYS if name in values}


async def add_input(
    session: AsyncSession,
    actor: Actor,
    application: Application,
    *,
    recommendation: str,
    ratings: Mapping[str, int],
    rationale: str,
    interview: Interview | None = None,
) -> HiringInput:
    if recommendation not in RECOMMENDATIONS:
        raise Invalid("invalid-recommendation", "Choose a recommendation", field="recommendation")
    reason = rationale.strip()
    if not reason or len(reason) > RATIONALE_MAX:
        raise Invalid(
            "invalid-rationale",
            f"Give your reasons, in at most {RATIONALE_MAX} characters",
            field="rationale",
        )
    rated = _ratings(ratings)
    about = interview or await finished_interview(session, application.id)
    row = HiringInput(
        organization_id=application.organization_id,
        application_id=application.id,
        interview_id=about.id if about is not None else None,
        author_id=actor.user_id,
        recommendation=recommendation,
        ratings=rated,
        rationale=reason,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    await record(
        session,
        actor,
        "hiring.input_added",
        "application",
        application.id,
        details={
            "candidate_id": str(application.candidate_id),
            "interview_id": str(row.interview_id) if row.interview_id else None,
            "recommendation": recommendation,
        },
    )
    return row


async def all_inputs(session: AsyncSession, application_id: UUID) -> list[HiringInput]:
    """Every submission, newest first."""
    rows = await session.scalars(
        select(HiringInput)
        .where(HiringInput.application_id == application_id)
        .order_by(HiringInput.created_at.desc(), HiringInput.id.desc())
    )
    return list(rows.all())


async def current_inputs(session: AsyncSession, application_id: UUID) -> list[HiringInput]:
    """The latest submission of each author, newest first."""
    seen: set[UUID] = set()
    current: list[HiringInput] = []
    for row in await all_inputs(session, application_id):
        if row.author_id not in seen:
            seen.add(row.author_id)
            current.append(row)
    return current
