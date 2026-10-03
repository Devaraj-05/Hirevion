"""Screening in the background, and the ranking (PRD §16, §18). A request queues one `screening`
event per application; the consumer screens each, then re-ranks the job. Once none of a job's
applications is waiting to be screened, its screened ones are `ranked`."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.actor import Actor
from hirevion_core.access.audit import record
from hirevion_core.ai import AiServices
from hirevion_core.db.session import Database
from hirevion_core.models import Application, Candidate, ScreeningResult
from hirevion_core.outbox import publish_event
from hirevion_core.screening.engine import record_stage, screen_application

SCREENING_TOPIC = "screening"
WAITING = ("uploaded", "parsed")
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


def _order_key(row: tuple[Application, ScreeningResult]) -> tuple[float, float, str]:
    application, result = row
    return (
        -result.score,
        -(result.semantic_similarity if result.semantic_similarity is not None else -1.0),
        application.created_at.isoformat(),
    )


async def rerank(session: AsyncSession, job_id: UUID) -> None:
    """Numbers the job's screened applications by score, then semantic similarity, then who
    applied first; and marks them `ranked` once nobody is waiting to be screened."""
    rows = [
        (row[0], row[1])
        for row in await session.execute(
            select(Application, ScreeningResult)
            .join(ScreeningResult, ScreeningResult.id == Application.screening_result_id)
            .where(Application.job_id == job_id)
        )
    ]
    for rank, (application, _) in enumerate(sorted(rows, key=_order_key), start=1):
        if application.rank != rank:
            application.rank = rank
    waiting = await session.scalar(
        select(func.count())
        .select_from(Application)
        .where(Application.job_id == job_id, Application.stage.in_(WAITING))
    )
    if not waiting:
        for application, result in rows:
            if application.stage == "screened":
                await record_stage(
                    session,
                    application,
                    "ranked",
                    "ranked",
                    score=result.score,
                    rank=application.rank,
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
