"""The recruitment dashboard's figures (PRD §10), within the reader's resource scope and the
page's seven filters, each counted from the data:

- **Open Jobs:** jobs with status `open`.
- **Active Candidates:** people with at least one application that is not decided (its hiring
  status is neither `selected` nor `rejected`). **Hiring Pipeline:** those applications, counted
  one by one (a person in two jobs is two there and one above).
- **Candidates Screened:** people with a screening result for an application.
  **Candidates Shortlisted:** people with an application whose hiring status is `shortlisted`.
- **Interviews Scheduled / Live / Completed:** interviews by status. **Pending Reviews:**
  finished interviews waiting for a decision. **Proctoring Alerts:** WARNING and CRITICAL events
  of those interviews that no one has reviewed yet.

Filters: *date* is when the job was made, the application came in or the interview's window
opens, whichever the figure counts; *recruiter*, *team*, *job* and *department* are the job's (the
interview's, for an interview); *candidate status* is the application's hiring status; *interview
status* is the interview's. A figure with no candidate or interview of its own counts a job or a
person when they have one in that state, so no filter is ignored.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, Select, and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from hirevion_core.access.scope import ResourceScope, job_scope_clause
from hirevion_core.hiring.workflow import FINISHED
from hirevion_core.interviews.assignment import InterviewFilters, interviews_statement
from hirevion_core.models import Application, Interview, Job, ProctorEvent

INTERVIEW_FIGURES: dict[str, tuple[str, ...]] = {
    "interviews_scheduled": ("scheduled", "invited"),
    "live_interviews": ("in_progress", "interrupted"),
    "completed_interviews": ("completed", "evaluating", "evaluated"),
}
DECIDED = ("selected", "rejected")
# Interviews that have ended and wait for a person to decide (see `reports.review`).
AWAITING = ("interview_completed", "additional_review")
ALERT_SEVERITIES = ("WARNING", "CRITICAL")


@dataclass(frozen=True, slots=True)
class DashboardFilters:
    date_from: datetime | None = None
    date_to: datetime | None = None
    recruiter_id: UUID | None = None
    team_id: UUID | None = None
    job_id: UUID | None = None
    department_id: UUID | None = None
    interview_status: str | None = None
    candidate_status: str | None = None


def _between(
    column: InstrumentedAttribute[datetime], filters: DashboardFilters
) -> list[ColumnElement[bool]]:
    found: list[ColumnElement[bool]] = []
    if filters.date_from is not None:
        found.append(column >= filters.date_from)
    if filters.date_to is not None:
        found.append(column < filters.date_to)
    return found


def _job_filters(filters: DashboardFilters) -> list[ColumnElement[bool]]:
    """The conditions on a job that the job, department, team and recruiter filters make."""
    found: list[ColumnElement[bool]] = []
    if filters.job_id is not None:
        found.append(Job.id == filters.job_id)
    if filters.department_id is not None:
        found.append(Job.department_id == filters.department_id)
    if filters.team_id is not None:
        found.append(Job.team_id == filters.team_id)
    return found


def _interview_filter(filters: DashboardFilters) -> ColumnElement[bool] | None:
    """Applications that have an interview in the state the interview-status filter names."""
    if filters.interview_status is None:
        return None
    return exists(
        select(Interview.id).where(
            Interview.application_id == Application.id,
            Interview.status == filters.interview_status,
        )
    )


def _applications(scope: ResourceScope, filters: DashboardFilters) -> Select[Application]:
    """The applications `scope` reaches that the filters keep."""
    statement = (
        select(Application)
        .join(Job, Job.id == Application.job_id)
        .where(job_scope_clause(scope), *_job_filters(filters))
        .where(*_between(Application.created_at, filters))
    )
    if filters.recruiter_id is not None:
        # Who looks after the candidate: the person named for them, else the job's recruiter.
        statement = statement.where(
            func.coalesce(Application.recruiter_id, Job.recruiter_id) == filters.recruiter_id
        )
    if filters.candidate_status is not None:
        statement = statement.where(Application.hiring_status == filters.candidate_status)
    having_interview = _interview_filter(filters)
    if having_interview is not None:
        statement = statement.where(having_interview)
    return statement


async def job_figures(
    session: AsyncSession, scope: ResourceScope, filters: DashboardFilters
) -> dict[str, int]:
    statement = (
        select(func.count())
        .select_from(Job)
        .where(Job.status == "open", job_scope_clause(scope), *_job_filters(filters))
        .where(*_between(Job.created_at, filters))
    )
    if filters.recruiter_id is not None:
        statement = statement.where(Job.recruiter_id == filters.recruiter_id)
    # A candidate or interview filter keeps the jobs that have one in that state.
    if filters.candidate_status is not None or filters.interview_status is not None:
        matching = select(Application.id).where(Application.job_id == Job.id)
        if filters.candidate_status is not None:
            matching = matching.where(Application.hiring_status == filters.candidate_status)
        having_interview = _interview_filter(filters)
        if having_interview is not None:
            matching = matching.where(having_interview)
        statement = statement.where(exists(matching))
    return {"open_jobs": int(await session.scalar(statement) or 0)}


async def candidate_figures(
    session: AsyncSession, scope: ResourceScope, filters: DashboardFilters
) -> dict[str, int]:
    applications = _applications(scope, filters).subquery()
    screened = applications.c.screening_result_id.is_not(None)
    active = applications.c.hiring_status.not_in(DECIDED)
    row = (
        await session.execute(
            select(
                func.count(applications.c.candidate_id.distinct()).filter(active),
                func.count(applications.c.candidate_id.distinct()).filter(screened),
                func.count(applications.c.candidate_id.distinct()).filter(
                    applications.c.hiring_status == "shortlisted"
                ),
                func.count().filter(active),
            )
        )
    ).one()
    return {
        "active_candidates": int(row[0]),
        "screened": int(row[1]),
        "shortlisted": int(row[2]),
        "in_pipeline": int(row[3]),
    }


def _interviews(
    scope: ResourceScope, filters: DashboardFilters, reviewer_only: UUID | None
) -> Select[Interview]:
    """The interviews `scope` reaches (or the reader reviews) that the filters keep."""
    statement = interviews_statement(
        scope,
        InterviewFilters(job_id=filters.job_id, status=filters.interview_status),
        reviewer_only=reviewer_only,
    ).where(*_between(Interview.starts_at, filters))
    if filters.recruiter_id is not None:
        statement = statement.where(Interview.recruiter_id == filters.recruiter_id)
    if filters.team_id is not None:
        statement = statement.where(Interview.team_id == filters.team_id)
    if filters.department_id is not None:
        statement = statement.where(
            Interview.job_id.in_(select(Job.id).where(Job.department_id == filters.department_id))
        )
    if filters.candidate_status is not None:
        statement = statement.where(
            Interview.application_id.in_(
                select(Application.id).where(Application.hiring_status == filters.candidate_status)
            )
        )
    return statement


async def interview_figures(
    session: AsyncSession,
    scope: ResourceScope,
    filters: DashboardFilters,
    *,
    reviewer_only: UUID | None = None,
) -> dict[str, int]:
    counted = _interviews(scope, filters, reviewer_only).subquery()
    rows = await session.execute(select(counted.c.status, func.count()).group_by(counted.c.status))
    by_status = {str(status): int(count) for status, count in rows}
    return {
        figure: sum(by_status.get(status, 0) for status in statuses)
        for figure, statuses in INTERVIEW_FIGURES.items()
    }


async def review_figures(
    session: AsyncSession,
    scope: ResourceScope,
    filters: DashboardFilters,
    *,
    reviewer_only: UUID | None = None,
    alerts: bool = True,
) -> dict[str, int]:
    """Pending reviews, and (with `alerts`) the proctoring alerts of the same interviews."""
    base = _interviews(scope, filters, reviewer_only).subquery()
    pending = await session.scalar(
        select(func.count())
        .select_from(base)
        .join(Application, Application.id == base.c.application_id)
        .where(base.c.status.in_(FINISHED), Application.hiring_status.in_(AWAITING))
    )
    figures = {"pending_reviews": int(pending or 0)}
    if alerts:
        count = await session.scalar(
            select(func.count())
            .select_from(ProctorEvent)
            .where(
                ProctorEvent.interview_id.in_(select(base.c.id)),
                and_(
                    ProctorEvent.severity.in_(ALERT_SEVERITIES),
                    ProctorEvent.review_status == "pending",
                ),
            )
        )
        figures["proctoring_alerts"] = int(count or 0)
    return figures
