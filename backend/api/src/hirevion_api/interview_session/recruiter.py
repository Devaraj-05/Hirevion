"""The recruiter's side of an interview session (SP-09): its transcript with the questions'
sources and the skills' coverage (PRD §36, §37, §43, §90's `GET /interviews/{id}/transcript`),
deciding accommodation requests, and the organisation's interview briefing (instructions and the
FAQ final questions are answered from)."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import select

from hirevion_api.access.deps import own_tenant
from hirevion_api.authz import Principal, requires
from hirevion_api.interview_session.schemas import (
    AccommodationDecision,
    AccommodationResponse,
    AnswerResponse,
    ArtifactLink,
    CoverageItem,
    FaqItem,
    InterviewBriefingSettings,
    TranscriptQuestion,
    TranscriptResponse,
    TranscriptSegmentResponse,
)
from hirevion_api.routing import api_router
from hirevion_core.access.scope import resource_scope
from hirevion_core.engine.completion import CompletionEvaluator
from hirevion_core.engine.state import InterviewState
from hirevion_core.interview_session import preparation
from hirevion_core.interview_session.briefing import briefing_settings, save_briefing_settings
from hirevion_core.interview_session.transcripts import ARTIFACTS, segments
from hirevion_core.interviews import assignment
from hirevion_core.models import (
    Accommodation,
    InterviewAnswer,
    InterviewQuestion,
    InterviewSession,
    Transcript,
)
from hirevion_core.storage.paths import interview_blob

router = api_router(tags=["interviews"])

Views = Annotated[Principal, requires("interviews.view")]
Manages = Annotated[Principal, requires("interviews.manage")]
ReadsBriefing = Annotated[
    Principal, requires("interviews.templates.view", "admin.organization.manage")
]
ManagesOrganization = Annotated[Principal, requires("admin.organization.manage")]


def _accommodation(row: Accommodation) -> AccommodationResponse:
    return AccommodationResponse(
        id=row.id,
        kinds=list(row.kinds),
        note=row.note,
        status=row.status,  # type: ignore[arg-type]
        approved_kinds=list(row.approved_kinds),
        decision_note=row.decision_note,
        decided_by=row.decided_by,
        decided_at=row.decided_at,
        created_at=row.created_at,
    )


def _artifacts(
    request: Request, organization_id: UUID, interview_id: UUID, saved: dict[str, Any]
) -> list[ArtifactLink]:
    storage = getattr(request.app.state, "storage", None)
    sign = getattr(storage, "download_url", None)
    if sign is None:
        return []
    links = []
    for kind, (filename, _) in ARTIFACTS.items():
        item = saved.get(kind)
        if not isinstance(item, dict):
            continue
        path = interview_blob(organization_id, interview_id, "transcript", filename)
        links.append(
            ArtifactLink(
                kind=kind,  # type: ignore[arg-type]
                url=sign(organization_id, path, filename=f"{interview_id}-{filename}"),
                bytes=int(item.get("bytes", 0)),
                sha256=str(item.get("sha256", "")),
            )
        )
    return links


@router.get("/interviews/{interview_id}/transcript")
async def interview_transcript(
    interview_id: UUID, request: Request, principal: Views
) -> TranscriptResponse:
    """Both sides of the interview, every question with its source and answers, the skills'
    coverage, and short-lived links to the JSON, VTT and TXT artifacts once they're written."""
    async with own_tenant(request, principal) as session:
        scope = await resource_scope(session, principal.user_id)
        interview = await assignment.get_interview(
            session, interview_id, scope, reviewer_only=principal.reviewer_only
        )
        questions = (
            await session.scalars(
                select(InterviewQuestion)
                .where(InterviewQuestion.interview_id == interview.id)
                .order_by(InterviewQuestion.position)
            )
        ).all()
        answers = (
            await session.scalars(
                select(InterviewAnswer)
                .where(InterviewAnswer.interview_id == interview.id)
                .order_by(InterviewAnswer.created_at)
            )
        ).all()
        rows = await segments(session, interview.id)
        row = await session.get(InterviewSession, interview.id)
        transcript = await session.get(Transcript, interview.id)
    by_question: dict[UUID, list[InterviewAnswer]] = {}
    for answer in answers:
        by_question.setdefault(answer.question_id, []).append(answer)
    state = InterviewState.from_json(row.state) if row is not None and row.state else None
    coverage = CompletionEvaluator().coverage(state) if state is not None else []
    return TranscriptResponse(
        interview_id=interview.id,
        status=interview.status,
        stage=state.stage if state is not None else None,
        transcript_status=transcript.status if transcript is not None else "none",  # type: ignore[arg-type]
        coverage=[
            CoverageItem(
                skill=item["skill"],
                required=item["required"],
                covered=item["covered"],
                asked=item["asked"],
                answered=item["answered"],
                planned=item["planned"],
            )
            for item in coverage
        ],
        questions=[
            TranscriptQuestion(
                id=q.id,
                position=q.position,
                kind=q.kind,
                stage=q.stage,
                skill=q.skill,
                difficulty=q.difficulty,
                type=q.type,
                text=q.text,
                source=q.source,
                source_ref=q.source_ref,
                parent_id=q.parent_id,
                status=q.status,
                asked_at=q.asked_at,
                answers=[
                    AnswerResponse(
                        mode=a.mode,  # type: ignore[arg-type]
                        text=a.text,
                        late=a.late,
                        flags=list(a.flags),
                        created_at=a.created_at,
                    )
                    for a in by_question.get(q.id, [])
                ],
            )
            for q in questions
        ],
        segments=[
            TranscriptSegmentResponse(
                seq=s.seq,
                speaker=s.speaker,  # type: ignore[arg-type]
                text=s.text,
                start_ms=s.start_ms,
                end_ms=s.end_ms,
                question_id=s.question_id,
                confidence=float(s.confidence) if s.confidence is not None else None,
            )
            for s in rows
        ],
        artifacts=_artifacts(request, interview.organization_id, interview.id, transcript.artifacts)
        if transcript is not None and transcript.status == "ready"
        else [],
    )


@router.get("/interviews/{interview_id}/accommodations")
async def list_accommodations(
    interview_id: UUID, request: Request, principal: Views
) -> list[AccommodationResponse]:
    """The candidate's accommodation requests and their decisions."""
    async with own_tenant(request, principal) as session:
        scope = await resource_scope(session, principal.user_id)
        interview = await assignment.get_interview(
            session, interview_id, scope, reviewer_only=principal.reviewer_only
        )
        rows = await preparation.list_accommodations(session, interview.id)
        return [_accommodation(row) for row in rows]


@router.post("/interviews/{interview_id}/accommodations/{accommodation_id}/decision")
async def decide_accommodation(
    interview_id: UUID,
    accommodation_id: UUID,
    body: AccommodationDecision,
    request: Request,
    principal: Manages,
) -> AccommodationResponse:
    """Approves some or all of what was asked for, or none (declined), before the interview."""
    async with own_tenant(request, principal) as session:
        scope = await resource_scope(session, principal.user_id)
        interview = await assignment.get_interview(session, interview_id, scope, lock=True)
        row = await preparation.decide_accommodation(
            session,
            principal.actor(request),
            interview,
            accommodation_id,
            approved=body.approved,
            note=body.note,
        )
        await session.flush()
        await session.refresh(row)
        return _accommodation(row)


@router.get("/organization/interview-briefing")
async def get_interview_briefing(
    request: Request, principal: ReadsBriefing
) -> InterviewBriefingSettings:
    """What candidates are told before an interview, and the FAQ the AI answers from."""
    async with own_tenant(request, principal) as session:
        saved = await briefing_settings(session)
    return InterviewBriefingSettings(
        instructions=saved["instructions"], faq=[FaqItem(**item) for item in saved["faq"]]
    )


@router.put("/organization/interview-briefing")
async def update_interview_briefing(
    body: InterviewBriefingSettings, request: Request, principal: ManagesOrganization
) -> InterviewBriefingSettings:
    async with own_tenant(request, principal) as session:
        saved = await save_briefing_settings(
            session,
            principal.actor(request),
            body.instructions,
            [item.model_dump() for item in body.faq],
        )
    return InterviewBriefingSettings(
        instructions=saved["instructions"], faq=[FaqItem(**item) for item in saved["faq"]]
    )
