"""`/api/v1/candidate-requests`: candidates' requests from the portal, for recruiters to act on
(master plan §6.3; ADR-0022), within their resource scope (ADR-0014)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_api.access.deps import own_tenant
from hirevion_api.authz import Principal, requires
from hirevion_api.pagination import Page, PageParams, page_params, paginate
from hirevion_api.portal.schemas import (
    CandidateRequestItem,
    CandidateRequestUpdate,
    RequestKind,
    RequestStatus,
)
from hirevion_api.routing import api_router
from hirevion_core.access.scope import resource_scope
from hirevion_core.candidate_portal import requests
from hirevion_core.candidate_portal.requests import RequestFilters
from hirevion_core.interviews.lifecycle import reference
from hirevion_core.models import Candidate, CandidateRequest, Interview

router = api_router(tags=["candidate-requests"])

Views = Annotated[Principal, requires("candidates.requests.view")]
Manages = Annotated[Principal, requires("candidates.requests.manage")]
Pages = Annotated[PageParams, Depends(page_params)]


async def _items(
    session: AsyncSession, rows: Sequence[CandidateRequest]
) -> list[CandidateRequestItem]:
    candidate_ids = {row.candidate_id for row in rows}
    interview_ids = {row.interview_id for row in rows if row.interview_id is not None}
    candidates = {
        candidate.id: candidate
        for candidate in (
            await session.scalars(select(Candidate).where(Candidate.id.in_(candidate_ids)))
        ).all()
    }
    found = await session.execute(
        select(Interview.id, Interview.number).where(Interview.id.in_(interview_ids))
    )
    numbers: dict[UUID, int] = {interview_id: number for interview_id, number in found.all()}
    return [
        CandidateRequestItem(
            id=row.id,
            reference=requests.reference(row.id),
            kind=row.kind,  # type: ignore[arg-type]
            status=row.status,  # type: ignore[arg-type]
            message=row.message,
            details=row.details,
            response=row.response,
            candidate_id=row.candidate_id,
            candidate_name=candidates[row.candidate_id].name,
            candidate_email=candidates[row.candidate_id].email,
            interview_id=row.interview_id,
            interview_reference=reference(numbers[row.interview_id])
            if row.interview_id in numbers
            else None,
            handled_by=row.handled_by,
            handled_at=row.handled_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


@router.get("/candidate-requests")
async def list_candidate_requests(
    request: Request,
    principal: Views,
    page: Pages,
    status: RequestStatus | None = None,
    kind: RequestKind | None = None,
    interview_id: UUID | None = None,
    candidate_id: Annotated[UUID | None, Query()] = None,
) -> Page[CandidateRequestItem]:
    """Requests of the candidates the reader reaches, newest first."""
    filters = RequestFilters(
        status=status, kind=kind, interview_id=interview_id, candidate_id=candidate_id
    )
    async with own_tenant(request, principal) as session:
        scope = await resource_scope(session, principal.user_id)
        rows, next_cursor = await paginate(
            session,
            requests.recruiter_statement(scope, filters),
            [CandidateRequest.created_at, CandidateRequest.id],
            page,
            descending=True,
        )
        return Page(items=await _items(session, rows), next_cursor=next_cursor)


@router.patch("/candidate-requests/{request_id}")
async def update_candidate_request(
    request_id: UUID, body: CandidateRequestUpdate, request: Request, principal: Manages
) -> CandidateRequestItem:
    """Moves a request on (in progress, resolved or declined), with a reply the candidate
    reads in the portal. A closed request stays closed (409)."""
    async with own_tenant(request, principal) as session:
        scope = await resource_scope(session, principal.user_id)
        row = await requests.update_request(
            session,
            principal.actor(request),
            scope,
            request_id,
            status=body.status,
            response=body.response,
        )
        await session.refresh(row)
        [item] = await _items(session, [row])
        return item
