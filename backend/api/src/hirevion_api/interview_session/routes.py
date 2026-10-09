"""The desktop's interview routes, as `docs/api/contracts/interview-session.md` writes them
(SP-09). Every call carries the interview-session token for the path's interview with a fresh
DPoP proof (ADR-0021); none takes a recruiter's cookie."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from fastapi import Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_api.candidate_auth.deps import InterviewSession, where
from hirevion_api.deps import get_db, get_redis
from hirevion_api.interview_session.schemas import (
    AccommodationBody,
    AccommodationCreated,
    AccommodationsSummary,
    AnswerBody,
    BriefingResponse,
    CompleteBody,
    CompleteResponse,
    ConsentBody,
    ConsentResponse,
    Notice,
    NoticeItem,
    QuestionState,
    SessionState,
    StartBody,
    StartResponse,
    StateResponse,
    SystemCheckBody,
    SystemCheckResponse,
    WorkspaceBody,
)
from hirevion_api.problems import ProblemError
from hirevion_api.ratelimit import enforce, rate_limited
from hirevion_api.routing import api_router
from hirevion_core.interview_session import preparation
from hirevion_core.interview_session.briefing import briefing
from hirevion_core.interview_session.conductor import Conductor, MediaUnavailable, SessionView
from hirevion_core.interview_session.media import MediaControl
from hirevion_core.interview_session.preparation import CheckReport, ConsentAnswer
from hirevion_core.interviews.lifecycle import By
from hirevion_core.models import Interview
from hirevion_core.ratelimit import RateRule

router = api_router(tags=["interview-session"])

# A turn costs a model call: a desktop answering faster than this is a script. The per-interview
# limit applies once the token is checked (so nobody else can spend it); the per-IP one is a
# ceiling high enough for a test centre's candidates behind one address.
ANSWERS_BY_INTERVIEW = RateRule("iv-answer", 30, 60)
ANSWERS_BY_IP = RateRule("iv-answer-ip", 600, 60)
PREPARATION_BY_IP = RateRule("iv-prepare", 300, 60)


def media(request: Request) -> MediaControl | None:
    return cast(MediaControl | None, getattr(request.app.state, "media", None))


def conductor(request: Request) -> Conductor:
    ai = getattr(request.app.state, "ai", None)
    return Conductor(
        get_db(request),
        get_redis(request),
        llm=ai.llm if ai is not None else None,
        media=media(request),
        origin="api",
    )


def _by(request: Request, principal: InterviewSession) -> By:
    place = where(request)
    return By("candidate", str(principal.account_id), place["ip"], place["user_agent"])


def state_body(view: SessionView) -> SessionState:
    question = view.question
    return SessionState(
        status=view.status,
        started_at=view.started_at,
        deadline_at=view.deadline_at,
        remaining_seconds=view.remaining_seconds,
        third_eye=view.third_eye,  # type: ignore[arg-type]
        workspace=view.workspace,  # type: ignore[arg-type]
        answer_mode=view.answer_mode,  # type: ignore[arg-type]
        question=QuestionState(
            id=UUID(question.id),
            index=question.index,
            text=question.text,
            type=question.type,
            time_limit_seconds=question.time_limit_seconds,
            workspace=question.workspace,  # type: ignore[arg-type]
            languages=question.languages,
        )
        if question is not None
        else None,
        voice=view.voice,  # type: ignore[arg-type]
        stage=view.stage,
        message=view.message,
        notice=view.notice,
    )


async def _load(session: AsyncSession, interview_id: UUID) -> Interview:
    interview = await session.get(Interview, interview_id)
    if interview is None:
        raise ProblemError(404, "interview-not-found", "No such interview")
    return interview


@router.get("/interviews/{interview_id}/briefing")
async def interview_briefing(
    interview_id: UUID, request: Request, principal: InterviewSession
) -> BriefingResponse:
    """§30's instructions and the itemised consent notice, before the system check."""
    async with get_db(request).tenant(principal.organization_id) as session:
        interview = await _load(session, interview_id)
        result = await briefing(session, interview)
    return BriefingResponse(
        instructions=result.instructions,
        mandatory_checks=result.mandatory_checks,
        notice=Notice(
            version=result.notice_version,
            items=[
                NoticeItem(purpose=i.purpose, text=i.text, required=i.required)
                for i in result.notice
            ],
        ),
        accommodations=AccommodationsSummary(requested=result.requested, approved=result.approved),
        answer_mode=result.answer_mode,
        third_eye=result.third_eye,  # type: ignore[arg-type]
        duration_minutes=result.duration_minutes,
        support_email=result.support_email,
    )


@router.post(
    "/interviews/{interview_id}/system-checks",
    status_code=201,
    dependencies=[Depends(rate_limited(PREPARATION_BY_IP))],
)
async def record_system_check(
    interview_id: UUID, body: SystemCheckBody, request: Request, principal: InterviewSession
) -> SystemCheckResponse:
    """The desktop's system check (§29); it passes when every mandatory check passed."""
    async with get_db(request).tenant(principal.organization_id) as session:
        interview = await _load(session, interview_id)
        row = await preparation.record_system_check(
            session,
            interview,
            app_version=body.app_version,
            os=body.os,
            results=[CheckReport(r.check, r.status, r.value, r.detail) for r in body.results],
        )
        return SystemCheckResponse(
            id=row.id, passed=row.passed, failed_mandatory=row.failed_mandatory
        )


@router.post(
    "/interviews/{interview_id}/consents",
    status_code=201,
    dependencies=[Depends(rate_limited(PREPARATION_BY_IP))],
)
async def record_consents(
    interview_id: UUID, body: ConsentBody, request: Request, principal: InterviewSession
) -> ConsentResponse:
    """The candidate's answer to each purpose of the current notice (§30, §83)."""
    place = where(request)
    async with get_db(request).tenant(principal.organization_id) as session:
        interview = await _load(session, interview_id)
        row = await preparation.record_consent(
            session,
            interview,
            notice_version=body.notice_version,
            answers=[ConsentAnswer(i.purpose, i.accepted) for i in body.items],
            ip=place["ip"],
            user_agent=place["user_agent"],
        )
        return ConsentResponse(id=row.id, complete=row.complete, missing=row.missing)


@router.post(
    "/interviews/{interview_id}/accommodations",
    status_code=201,
    dependencies=[Depends(rate_limited(PREPARATION_BY_IP))],
)
async def request_accommodation(
    interview_id: UUID, body: AccommodationBody, request: Request, principal: InterviewSession
) -> AccommodationCreated:
    """Asks for accommodations; a recruiter decides in the web app."""
    async with get_db(request).tenant(principal.organization_id) as session:
        interview = await _load(session, interview_id)
        row = await preparation.request_accommodation(
            session, interview, body.kinds, body.note, _by(request, principal)
        )
        return AccommodationCreated(id=row.id, status=row.status)  # type: ignore[arg-type]


@router.post("/interviews/{interview_id}/start")
async def start_interview(
    interview_id: UUID, body: StartBody, request: Request, principal: InterviewSession
) -> StartResponse:
    """Starts the interview, or resumes it after a disconnect under its resume policy; returns
    the LiveKit room and a participant token that can do nothing else."""
    if media(request) is None:
        raise ProblemError(503, "media-unavailable", "The interview service isn't available")
    try:
        result = await conductor(request).start(
            principal.organization_id,
            interview_id,
            account_id=principal.account_id,
            system_check_id=body.system_check_id,
            consent_id=body.consent_id,
            token_expires_at=principal.claims.expires_at,
            by=_by(request, principal),
        )
    except MediaUnavailable as error:
        raise ProblemError(
            503, "media-unavailable", "The interview service isn't available; try again"
        ) from error
    token = result.media
    if token is None:
        raise ProblemError(503, "media-unavailable", "The interview service isn't available")
    return StartResponse(
        livekit_url=token.url,
        room=token.room,
        participant_identity=token.identity,
        participant_token=token.token,
        token_expires_at=token.expires_at,
        state=state_body(result.view),
    )


@router.get("/interviews/{interview_id}/session")
async def interview_session_state(
    interview_id: UUID, request: Request, principal: InterviewSession
) -> StateResponse:
    """The interview's state, for recovery after the app restarts."""
    view = await conductor(request).session_state(principal.organization_id, interview_id)
    return StateResponse(state=state_body(view))


@router.post(
    "/interviews/{interview_id}/answer",
    status_code=202,
    dependencies=[Depends(rate_limited(ANSWERS_BY_IP))],
)
async def answer_question(
    interview_id: UUID,
    body: AnswerBody,
    request: Request,
    response: Response,
    principal: InterviewSession,
) -> StateResponse:
    """A typed answer to the open question (PRD §90's text-answer mode). In text mode the state
    holds the next question; in voice mode the agent speaks it."""
    await enforce(request, response, ANSWERS_BY_INTERVIEW, str(interview_id))
    result = await conductor(request).answer(
        principal.organization_id,
        interview_id,
        body.question_id,
        body.text,
        mode="text",
        by=_by(request, principal),
    )
    return StateResponse(state=state_body(result.view))


@router.post(
    "/interviews/{interview_id}/workspace",
    status_code=202,
    dependencies=[Depends(rate_limited(ANSWERS_BY_IP))],
)
async def save_workspace(
    interview_id: UUID,
    body: WorkspaceBody,
    request: Request,
    response: Response,
    principal: InterviewSession,
) -> None:
    """A snapshot of the code or whiteboard for a question."""
    await enforce(request, response, ANSWERS_BY_INTERVIEW, f"ws:{interview_id}")
    await conductor(request).workspace(
        principal.organization_id,
        interview_id,
        body.question_id,
        kind=body.kind,
        language=body.language,
        content=body.content,
    )


@router.post("/interviews/{interview_id}/complete")
async def complete_interview(
    interview_id: UUID, body: CompleteBody, request: Request, principal: InterviewSession
) -> CompleteResponse:
    """Ends the interview; the desktop then drains its upload queue before closing."""
    status = await conductor(request).complete(
        principal.organization_id, interview_id, body.reason, by=_by(request, principal)
    )
    return CompleteResponse(status=status)
