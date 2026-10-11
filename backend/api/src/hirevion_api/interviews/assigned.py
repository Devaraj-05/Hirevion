"""Interviews (PRD §24, §25): assigning them singly or in bulk, the list and detail, sending the
invitation, rescheduling, cancelling and reviewers. Everyone reads within their resource scope;
someone who can't see candidates (the interviewer role) sees only the interviews they review."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_api.access.deps import idempotency_scope, own_tenant
from hirevion_api.authz import Principal, requires
from hirevion_api.idempotency import Idempotency, idempotency
from hirevion_api.interviews.assigned_schemas import (
    AssignBody,
    BulkInterviewCreate,
    BulkInterviewResult,
    CancelBody,
    InterviewCreate,
    InterviewEventResponse,
    InterviewResponse,
    InterviewStatus,
    InterviewSummary,
    InvitationResponse,
    PersonRef,
    RescheduleBody,
    ReviewersBody,
    SkippedApplication,
    StatusGroup,
)
from hirevion_api.pagination import Page, PageParams, page_params, paginate
from hirevion_api.problems import ProblemError
from hirevion_api.routing import api_router
from hirevion_core.access.scope import ResourceScope, resource_scope
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.interviews import assignment
from hirevion_core.interviews.assignment import Assignment, InterviewDetail, InterviewFilters
from hirevion_core.interviews.lifecycle import reference
from hirevion_core.models import Candidate, Interview, Job

router = api_router(tags=["interviews"])

Views = Annotated[Principal, requires("interviews.view")]
Manages = Annotated[Principal, requires("interviews.manage")]
Idempotent = Annotated[Idempotency, Depends(idempotency)]
Pages = Annotated[PageParams, Depends(page_params)]


def _settings(request: Request) -> IdentitySettings:
    settings: IdentitySettings = request.app.state.identity
    return settings


def _assignment(body: AssignBody, application_ids: list[UUID]) -> Assignment:
    return Assignment(
        application_ids=application_ids,
        starts_at=body.starts_at,
        expires_at=body.expires_at,
        template_id=body.template_id,
        template_version=body.template_version,
        timezone=body.timezone,
        reviewer_ids=body.reviewer_ids,
        invite=body.invite,
    )


def _summary(interview: Interview, candidate: Candidate, job: Job) -> InterviewSummary:
    return InterviewSummary(
        id=interview.id,
        reference=reference(interview.number),
        status=interview.status,  # type: ignore[arg-type]
        candidate=PersonRef(id=candidate.id, name=candidate.name),
        job_id=job.id,
        job_title=job.title,
        application_id=interview.application_id,
        template_id=interview.template_id,
        template_version=interview.template_version,
        starts_at=interview.starts_at,
        expires_at=interview.expires_at,
        timezone=interview.timezone,
        duration_minutes=interview.duration_minutes,
        proctoring_level=str(interview.policy.get("proctoring_level", "standard")),
        third_eye=str(interview.policy.get("third_eye", "optional")),
        created_at=interview.created_at,
        updated_at=interview.updated_at,
    )


def _response(detail: InterviewDetail) -> InterviewResponse:
    interview = detail.interview
    return InterviewResponse(
        **_summary(interview, detail.candidate, detail.job).model_dump(),
        candidate_email=detail.candidate.email,
        template_name=detail.template_name,
        policy=interview.policy,
        questions=interview.questions,
        reviewers=[PersonRef(id=user.id, name=user.name) for user in detail.reviewers],
        events=[
            InterviewEventResponse(
                id=event.id,
                action=event.action,
                from_status=event.from_status,  # type: ignore[arg-type]
                to_status=event.to_status,  # type: ignore[arg-type]
                reason=event.reason,
                actor_type=event.actor_type,  # type: ignore[arg-type]
                actor_id=event.actor_id,
                details=event.details,
                created_at=event.created_at,
            )
            for event in detail.events
        ],
        invitations=[
            InvitationResponse(
                id=item.id,
                kind=item.kind,  # type: ignore[arg-type]
                sent_to=item.sent_to,
                locale=item.locale,
                contents=item.contents,
                created_at=item.created_at,
            )
            for item in detail.invitations
        ],
        invited_at=interview.invited_at,
        started_at=interview.started_at,
        completed_at=interview.completed_at,
        ended_at=interview.ended_at,
        cancel_reason=interview.cancel_reason,
        reschedule_count=interview.reschedule_count,
    )


async def _summaries(session: AsyncSession, rows: list[Interview]) -> list[InterviewSummary]:
    if not rows:
        return []
    candidates = {
        row.id: row
        for row in await session.scalars(
            select(Candidate).where(Candidate.id.in_({r.candidate_id for r in rows}))
        )
    }
    jobs = {
        row.id: row
        for row in await session.scalars(select(Job).where(Job.id.in_({r.job_id for r in rows})))
    }
    return [_summary(row, candidates[row.candidate_id], jobs[row.job_id]) for row in rows]


async def _reloaded(
    session: AsyncSession, principal: Principal, scope: ResourceScope, interview_id: UUID
) -> InterviewResponse:
    await session.flush()
    session.expire_all()
    interview = await assignment.get_interview(
        session, interview_id, scope, reviewer_only=principal.reviewer_only
    )
    return _response(await assignment.describe(session, interview))


@router.get("/interviews")
async def list_interviews(
    request: Request,
    principal: Views,
    page: Pages,
    status_group: Annotated[
        StatusGroup | None, Query(description="The /interviews tab: upcoming, live or completed.")
    ] = None,
    status: InterviewStatus | None = None,
    job_id: UUID | None = None,
    candidate_id: UUID | None = None,
    q: Annotated[
        str | None,
        Query(max_length=200, description="Part of the candidate's name or the job, or IV-42."),
    ] = None,
) -> Page[InterviewSummary]:
    """Interviews the reader reaches; upcoming ones soonest first, the others latest first."""
    filters = InterviewFilters(
        status_group=status_group, status=status, job_id=job_id, candidate_id=candidate_id, query=q
    )
    async with own_tenant(request, principal) as session:
        scope = await resource_scope(session, principal.user_id)
        upcoming = status_group == "upcoming"
        rows, next_cursor = await paginate(
            session,
            assignment.interviews_statement(scope, filters, reviewer_only=principal.reviewer_only),
            [Interview.starts_at if upcoming else Interview.updated_at, Interview.id],
            page,
            descending=not upcoming,
        )
        return Page(items=await _summaries(session, list(rows)), next_cursor=next_cursor)


@router.post("/interviews", status_code=201)
async def create_interview(
    body: InterviewCreate, request: Request, principal: Manages, idem: Idempotent
) -> InterviewResponse:
    """Assigns one candidate an interview (PRD §24) and, unless asked not to, invites them."""
    async with own_tenant(request, principal) as session:

        async def create() -> InterviewResponse:
            scope = await resource_scope(session, principal.user_id)
            result = await assignment.assign(
                session,
                principal.actor(request),
                _assignment(body, [body.application_id]),
                scope,
                settings=_settings(request),
            )
            if result.skipped:
                skipped = result.skipped[0]
                if skipped.code == "application-not-found":
                    raise ProblemError(404, skipped.code, skipped.reason)
                if skipped.code in assignment.INPUT_CODES:
                    raise ProblemError(422, skipped.code, skipped.reason, field="expires_at")
                raise ProblemError(409, skipped.code, skipped.reason)
            return await _reloaded(session, principal, scope, result.created[0].id)

        return await idem.run(
            session, principal.organization_id, idempotency_scope(principal), create
        )


@router.post("/interviews/bulk")
async def create_interviews(
    body: BulkInterviewCreate, request: Request, principal: Manages
) -> BulkInterviewResult:
    """Assigns up to 200 candidates the same interview at once; those that can't have one are
    listed with the reason."""
    async with own_tenant(request, principal) as session:
        scope = await resource_scope(session, principal.user_id)
        result = await assignment.assign(
            session,
            principal.actor(request),
            _assignment(body, body.application_ids),
            scope,
            settings=_settings(request),
        )
        # Reload the new rows: the database set their timestamps.
        created_ids = [interview.id for interview in result.created]
        await session.flush()
        session.expire_all()
        created = (
            await session.scalars(
                select(Interview).where(Interview.id.in_(created_ids)).order_by(Interview.number)
            )
        ).all()
        return BulkInterviewResult(
            created=await _summaries(session, list(created)),
            skipped=[
                SkippedApplication(
                    application_id=item.application_id, code=item.code, reason=item.reason
                )
                for item in result.skipped
            ],
        )


@router.get("/interviews/{interview_id}")
async def get_interview(
    interview_id: UUID, request: Request, principal: Views
) -> InterviewResponse:
    """The interview with its pinned policy, reviewers, history and the invitations sent."""
    async with own_tenant(request, principal) as session:
        scope = await resource_scope(session, principal.user_id)
        return await _reloaded(session, principal, scope, interview_id)


async def _locked(
    session: AsyncSession, principal: Principal, interview_id: UUID
) -> tuple[ResourceScope, Interview]:
    scope = await resource_scope(session, principal.user_id)
    interview = await assignment.get_interview(session, interview_id, scope, lock=True)
    return scope, interview


@router.post("/interviews/{interview_id}/invitation")
async def send_invitation(
    interview_id: UUID, request: Request, principal: Manages
) -> InterviewResponse:
    """Sends a scheduled interview's invitation, or an invited one's again (with a fresh link)."""
    async with own_tenant(request, principal) as session:
        scope, interview = await _locked(session, principal, interview_id)
        await assignment.invite(
            session, principal.actor(request), interview, settings=_settings(request)
        )
        return await _reloaded(session, principal, scope, interview_id)


@router.post("/interviews/{interview_id}/reschedule")
async def reschedule_interview(
    interview_id: UUID, body: RescheduleBody, request: Request, principal: Manages
) -> InterviewResponse:
    """Gives an interview that hasn't started a new window, and tells the candidate."""
    async with own_tenant(request, principal) as session:
        scope, interview = await _locked(session, principal, interview_id)
        await assignment.reschedule(
            session,
            principal.actor(request),
            interview,
            body.starts_at,
            body.expires_at,
            reason=body.reason,
            settings=_settings(request),
        )
        return await _reloaded(session, principal, scope, interview_id)


@router.post("/interviews/{interview_id}/cancel")
async def cancel_interview(
    interview_id: UUID, body: CancelBody, request: Request, principal: Manages
) -> InterviewResponse:
    """Cancels an interview that hasn't started; an invited candidate is told why."""
    async with own_tenant(request, principal) as session:
        scope, interview = await _locked(session, principal, interview_id)
        await assignment.cancel(
            session,
            principal.actor(request),
            interview,
            reason=body.reason,
            settings=_settings(request),
        )
        return await _reloaded(session, principal, scope, interview_id)


@router.put("/interviews/{interview_id}/reviewers")
async def set_interview_reviewers(
    interview_id: UUID, body: ReviewersBody, request: Request, principal: Manages
) -> InterviewResponse:
    """Replaces who reviews the interview."""
    async with own_tenant(request, principal) as session:
        scope, interview = await _locked(session, principal, interview_id)
        await assignment.set_reviewers(
            session, principal.actor(request), interview, body.reviewer_ids
        )
        return await _reloaded(session, principal, scope, interview_id)
