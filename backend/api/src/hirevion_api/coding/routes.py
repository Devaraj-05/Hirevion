"""The desktop's coding console (SP-16; `docs/api/contracts/coding.md`; ADR-0033).

The candidate types the answer to the coding question in a plain text box, labels its language
and submits it; the code is stored and reviewed after the interview, never run. The console saves
drafts with `POST /interviews/{id}/workspace` (interview-session.md) and reports its integrity
events here. Every call carries the interview-session token for the path's interview with a fresh
DPoP proof (ADR-0021).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, Request, Response

from hirevion_api.candidate_auth.deps import InterviewSession
from hirevion_api.coding.schemas import (
    CodingQuestionBody,
    CodingQuestionResponse,
    Draft,
    Submission,
    SubmissionBody,
    SubmissionResponse,
    TelemetryBody,
    TelemetryResponse,
)
from hirevion_api.deps import get_db
from hirevion_api.interview_session.routes import (
    ANSWERS_BY_IP,
    _by,
    conductor,
    interview_clock,
    state_body,
)
from hirevion_api.ratelimit import enforce, rate_limited
from hirevion_api.routing import api_router
from hirevion_core.access.errors import NotFound
from hirevion_core.coding import console
from hirevion_core.models import Interview
from hirevion_core.ratelimit import RateRule

router = api_router(tags=["coding"])

SUBMISSIONS_BY_INTERVIEW = RateRule("iv-code-submit", 10, 60)
TELEMETRY_BY_INTERVIEW = RateRule("iv-code-telemetry", 60, 60)


@router.get("/interviews/{interview_id}/coding")
async def coding_question(
    interview_id: UUID, request: Request, principal: InterviewSession
) -> CodingQuestionResponse:
    """The open coding question for the console: its text, the languages to choose from, any
    starter code and the last saved draft; `question` is null when the open question isn't one."""
    state = await conductor(request).load_state(principal.organization_id, interview_id)
    if state is None:
        return CodingQuestionResponse(question=None)
    async with get_db(request).tenant(principal.organization_id) as session:
        view = await console.coding_question(session, state.current)
    if view is None:
        return CodingQuestionResponse(question=None)
    return CodingQuestionResponse(
        question=CodingQuestionBody(
            question_id=UUID(view.question_id),
            text=view.text,
            languages=view.languages,  # type: ignore[arg-type]
            starter_code=view.starter_code,
            time_limit_seconds=view.time_limit_seconds,
            asked_at=view.asked_at,
            draft=Draft(
                language=view.draft.language,
                content=view.draft.content,
                saved_at=view.draft.saved_at,
            )
            if view.draft is not None
            else None,
        )
    )


@router.post(
    "/interviews/{interview_id}/coding/submissions",
    status_code=202,
    dependencies=[Depends(rate_limited(ANSWERS_BY_IP))],
)
async def submit_code(
    interview_id: UUID,
    body: SubmissionBody,
    request: Request,
    response: Response,
    principal: InterviewSession,
) -> SubmissionResponse:
    """Submits the coding question's answer. It becomes the question's final code (never run;
    reviewed after the interview), the question closes and the interview moves on."""
    await enforce(request, response, SUBMISSIONS_BY_INTERVIEW, str(interview_id))
    result, saved = await conductor(request).submit_code(
        principal.organization_id,
        interview_id,
        body.question_id,
        language=body.language,
        code=body.code,
        by=_by(request, principal),
    )
    return SubmissionResponse(
        submission=Submission(
            id=saved.id,
            question_id=saved.question_id,
            language=body.language,
            size=saved.size,
            sha256=saved.sha256,
            source="submitted",
            submitted_at=saved.created_at,
        ),
        state=state_body(result.view),
    )


@router.post(
    "/interviews/{interview_id}/coding/telemetry",
    status_code=202,
    dependencies=[Depends(rate_limited(ANSWERS_BY_IP))],
)
async def coding_telemetry(
    interview_id: UUID,
    body: TelemetryBody,
    request: Request,
    response: Response,
    principal: InterviewSession,
) -> TelemetryResponse:
    """A batch of the console's integrity events (PRD §48): typing started and stopped, paste,
    copy, cut, focus and blur. Clipboard events carry a length, never text; there are no
    keystrokes."""
    await enforce(request, response, TELEMETRY_BY_INTERVIEW, str(interview_id))
    async with get_db(request).tenant(principal.organization_id) as session:
        interview = await session.get(Interview, interview_id)
        if interview is None:
            raise NotFound("interview-not-found", "No such interview")
        accepted = await console.record_telemetry(
            session,
            interview,
            body.question_id,
            [console.TelemetryEvent(e.kind, e.at, e.chars) for e in body.events],
            now=interview_clock(request)(),
        )
    return TelemetryResponse(accepted=accepted)
