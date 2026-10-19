"""Screening in the background, and the ranking (PRD §16, §18). A request queues one `screening`
event per application; the consumer screens each, then re-ranks the job. Once none of a job's
applications is waiting to be screened, its screened ones are `ranked`."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.actor import Actor
from hirevion_core.access.audit import record
from hirevion_core.ai import AiServices
from hirevion_core.db.session import Database
from hirevion_core.models import Application, Candidate, ScreeningResult
from hirevion_core.outbox import publish_event
from hirevion_core.screening.engine import SCREENABLE, record_stage, screen_application

SCREENING_TOPIC = "screening"
WAITING = SCREENABLE
NOT_SCREENABLE = ("uploaded",)


async def request_screening(
    session: AsyncSession,
    actor: Actor,
    job_id: UUID,
    application_ids: Sequence[UUID] | None = None,
) -> int:
    """Queues the job's applications (or the given ones) for screening; a result that's still
    current is reused without an AI call, so screening again is cheap."""
    statement = select(Application).where(
        Application.job_id == job_id, Application.stage.not_in(NOT_SCREENABLE)
    )
    if application_ids is not None:
        statement = statement.where(Application.id.in_(application_ids))
    applications = (await session.scalars(statement)).all()
    for application in applications:
        await publish_event(
            session,
            actor.organization_id,
            SCREENING_TOPIC,
            {"action": "screen", "application_id": str(application.id), "job_id": str(job_id)},
            key=str(application.id),
        )
    await record(
        session,
        actor,
        "screening.requested",
        "job",
        job_id,
        details={"applications": len(applications)},
    )
    return len(applications)


def _order_key(row: Any) -> tuple[int, float, datetime, str]:
    """Score, then semantic similarity, then who applied first, then the id: no two applications
    are ever equal, so the order is the same every time."""
    similarity = row.semantic_similarity
    return (
        -row.score,
        -(similarity if similarity is not None else -1.0),
        row.created_at,
        str(row.id),
    )


async def rerank(session: AsyncSession, job_id: UUID) -> None:
    """Numbers the job's screened applications by score, then semantic similarity, then who
    applied first; and marks them `ranked` once nobody is waiting to be screened.

    One re-rank of a job runs at a time (two at once each saw only their own committed rows and
    numbered them alike), and only applications still `screened` become `ranked`: a decision a
    recruiter has just made is never written over."""
    await session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(str(job_id), 0))))
    rows = (
        await session.execute(
            select(
                Application.id,
                Application.rank,
                Application.created_at,
                ScreeningResult.score,
                ScreeningResult.semantic_similarity,
            )
            .join(ScreeningResult, ScreeningResult.id == Application.screening_result_id)
            .where(Application.job_id == job_id)
        )
    ).all()
    ranks: dict[UUID, int] = {}
    scores: dict[UUID, int] = {}
    for rank, row in enumerate(sorted(rows, key=_order_key), start=1):
        ranks[row.id], scores[row.id] = rank, row.score
        if row.rank != rank:
            await session.execute(
                update(Application).where(Application.id == row.id).values(rank=rank)
            )
    waiting = await session.scalar(
        select(func.count())
        .select_from(Application)
        .where(Application.job_id == job_id, Application.stage.in_(WAITING))
    )
    if not waiting:
        screened = await session.scalars(
            select(Application)
            .where(Application.job_id == job_id, Application.stage == "screened")
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        for application in screened:
            if application.id in ranks:
                await record_stage(
                    session,
                    application,
                    "ranked",
                    "ranked",
                    score=scores[application.id],
                    rank=ranks[application.id],
                )
    await session.flush()


async def handle_screening_event(
    db: Database, ai: AiServices, organization_id: UUID, payload: dict[str, Any]
) -> None:
    if payload.get("action") != "screen":
        return
    result = await screen_application(db, ai, organization_id, UUID(payload["application_id"]))
    if result is None:
        return
    async with db.tenant(organization_id) as session:
        await rerank(session, result.job_id)


async def give_up_screening(db: Database, organization_id: UUID, payload: dict[str, Any]) -> None:
    """After the last try: the application can't be screened (the AI refused it every time, the
    budget is spent). It goes to a person, who sees why in its history, and the job's ranking
    carries on without it; "screen again" tries it afresh."""
    if payload.get("action") != "screen":
        return
    async with db.tenant(organization_id) as session:
        application = await session.get(Application, UUID(payload["application_id"]))
        if application is None or application.stage not in SCREENABLE:
            return
        await record_stage(
            session,
            application,
            "review",
            "screening_failed",
            reason="Screening could not be completed: review this candidate by hand",
        )
        await rerank(session, application.job_id)


async def ranking(
    session: AsyncSession, job_id: UUID
) -> list[tuple[Application, ScreeningResult | None, Candidate]]:
    """Every application of the job: ranked ones in order, then those not screened yet."""
    rows = await session.execute(
        select(Application, ScreeningResult, Candidate)
        .join(Candidate, Candidate.id == Application.candidate_id)
        .outerjoin(ScreeningResult, ScreeningResult.id == Application.screening_result_id)
        .where(Application.job_id == job_id)
        .order_by(Application.rank.asc().nulls_last(), Application.created_at)
    )
    return [(row[0], row[1], row[2]) for row in rows]
