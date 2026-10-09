"""The recruitment dashboard's figures (PRD §10), within the reader's resource scope and the
page's filters. Each module adds its figures as it lands: interviews here (SP-07a); jobs and
candidates with H0.2; reviews and proctoring alerts with SP-17 and SP-14.

The date filter applies to when the interview's window opens.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.scope import ResourceScope
from hirevion_core.interviews.assignment import InterviewFilters, interviews_statement
from hirevion_core.models import Interview, Job

INTERVIEW_FIGURES: dict[str, tuple[str, ...]] = {
    "interviews_scheduled": ("scheduled", "invited"),
    "live_interviews": ("in_progress", "interrupted"),
    "completed_interviews": ("completed", "evaluating", "evaluated"),
}


@dataclass(frozen=True, slots=True)
class DashboardFilters:
    date_from: datetime | None = None
    date_to: datetime | None = None
    recruiter_id: UUID | None = None
    team_id: UUID | None = None
    job_id: UUID | None = None
    department_id: UUID | None = None
    interview_status: str | None = None


async def interview_figures(
    session: AsyncSession,
    scope: ResourceScope,
    filters: DashboardFilters,
    *,
    reviewer_only: UUID | None = None,
) -> dict[str, int]:
    statement = interviews_statement(
        scope,
        InterviewFilters(job_id=filters.job_id, status=filters.interview_status),
        reviewer_only=reviewer_only,
    )
    if filters.date_from is not None:
        statement = statement.where(Interview.starts_at >= filters.date_from)
    if filters.date_to is not None:
        statement = statement.where(Interview.starts_at < filters.date_to)
    if filters.recruiter_id is not None:
        statement = statement.where(Interview.recruiter_id == filters.recruiter_id)
    if filters.team_id is not None:
        statement = statement.where(Interview.team_id == filters.team_id)
    if filters.department_id is not None:
        statement = statement.where(
            Interview.job_id.in_(select(Job.id).where(Job.department_id == filters.department_id))
        )
    counted = statement.subquery()
    rows = await session.execute(select(counted.c.status, func.count()).group_by(counted.c.status))
    by_status = {str(status): int(count) for status, count in rows}
    return {
        figure: sum(by_status.get(status, 0) for status in statuses)
        for figure, statuses in INTERVIEW_FIGURES.items()
    }
