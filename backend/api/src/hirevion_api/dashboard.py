"""The recruitment dashboard (PRD §10): its figures, under the page's seven filters."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Query, Request
from pydantic import AwareDatetime

from hirevion_api.access.deps import own_tenant
from hirevion_api.authz import Principal, requires
from hirevion_api.interviews.assigned_schemas import DashboardSummary, InterviewStatus
from hirevion_api.routing import api_router
from hirevion_core.access.scope import resource_scope
from hirevion_core.dashboard import DashboardFilters, interview_figures
from hirevion_core.reports.review import pending_count

router = api_router(tags=["dashboard"])

ViewsDashboard = Annotated[Principal, requires("dashboard.view")]


@router.get("/dashboard")
async def get_dashboard(
    request: Request,
    principal: ViewsDashboard,
    date_from: Annotated[AwareDatetime | None, Query(alias="from")] = None,
    date_to: Annotated[AwareDatetime | None, Query(alias="to")] = None,
    recruiter: UUID | None = None,
    team: UUID | None = None,
    job: UUID | None = None,
    department: UUID | None = None,
    interview_status: Annotated[InterviewStatus | None, Query(alias="interviewStatus")] = None,
) -> DashboardSummary:
    """The figures within the reader's scope that have data so far."""
    filters = DashboardFilters(
        date_from=date_from,
        date_to=date_to,
        recruiter_id=recruiter,
        team_id=team,
        job_id=job,
        department_id=department,
        interview_status=interview_status,
    )
    reviewer_only = principal.reviewer_only
    async with own_tenant(request, principal) as session:
        scope = await resource_scope(session, principal.user_id)
        figures = await interview_figures(session, scope, filters, reviewer_only=reviewer_only)
        pending = await pending_count(session, scope, reviewer_only=reviewer_only)
    return DashboardSummary(**figures, pending_reviews=pending)
