"""Candidate 360 (SP-17; PRD §19, §20, §98): the candidate's whole file, tab by tab, and the
unified timeline. Parts a reader's permissions don't cover are left out of the answer, and the
web hides the tabs that would be empty."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import Query, Request
from sqlalchemy import select

from hirevion_api.access.deps import own_tenant
from hirevion_api.authz import Principal, requires
from hirevion_api.candidate360 import schemas
from hirevion_api.review.schemas import NoteResponse, ScoreValueResponse
from hirevion_api.routing import api_router
from hirevion_core.access.scope import resource_scope
from hirevion_core.hiring.scores import ScoreValue
from hirevion_core.interviews.lifecycle import reference
from hirevion_core.models import Interview, User
from hirevion_core.reports.candidate360 import Candidate360, load_candidate_360
from hirevion_core.reports.data import InterviewData
from hirevion_core.reports.review import track_kind
from hirevion_core.reports.timeline import SOURCES, candidate_entries, track_label

router = api_router(tags=["candidates"])

ViewsCandidates = Annotated[Principal, requires("candidates.view")]
TIMELINE_LIMIT = 200
INTERVIEW_SOURCES = frozenset({"interview", "transcript", "coding", "evaluation", "recording"})


def _score_value(item: ScoreValue) -> ScoreValueResponse:
    """The score and the AI's; a change's reason is in the review workspace."""
    return ScoreValueResponse(ai=item.ai, value=item.value, change=None)


def _interview_item(
    data: InterviewData, c360: Candidate360, principal: Principal
) -> schemas.InterviewHistoryItem:
    interview = data.interview
    view = data.scores
    summary = data.evaluation.summary if data.evaluation is not None else {}
    can_proctoring = "reports.proctoring.view" in principal.permissions
    counts = {"CRITICAL": 0, "WARNING": 0, "INFO": 0}
    for event in data.events:
        counts[event.severity] = counts.get(event.severity, 0) + 1
    report = c360.candidate_reports.get(interview.id)
    return schemas.InterviewHistoryItem(
        interview_id=interview.id,
        reference=reference(interview.number),
        application_id=interview.application_id,
        job_id=data.job.id,
        job_title=data.job.title,
        template_name=data.template_name,
        status=interview.status,
        hiring_status=data.application.hiring_status,  # type: ignore[arg-type]
        starts_at=interview.starts_at,
        started_at=interview.started_at,
        completed_at=interview.completed_at,
        evaluation=schemas.EvaluationBrief(
            state="ready" if view is not None else "none",
            overall=_score_value(view.overall) if view else None,
            communication=_score_value(view.communication) if view else None,
            skills=[
                schemas.SkillScore(skill=name, score=_score_value(item))
                for name, item in (view.skills.items() if view else [])
            ],
            flags=list(data.evaluation.flags) if data.evaluation else [],
            strengths=[str(item["text"]) for item in summary.get("strengths", [])],
            knowledge_gaps=[str(item["text"]) for item in summary.get("knowledge_gaps", [])],
        ),
        proctoring=schemas.EventCounts(
            critical=counts["CRITICAL"],
            warning=counts["WARNING"],
            info=counts["INFO"],
            reviewed=len(data.reviews),
        )
        if can_proctoring
        else None,
        recordings=[
            schemas.RecordingBrief(
                track=recording.track,
                kind=track_kind(recording.track),  # type: ignore[arg-type]
                label=track_label(recording.track),
                status=recording.status,
                duration_ms=recording.duration_ms,
            )
            for recording in data.recordings
        ],
        candidate_report_status=report.status if report is not None else "none",  # type: ignore[arg-type]
        code_snapshots=len(data.snapshots),
        exports=[
            schemas.ExportBrief(id=row.id, kind=row.kind, created_at=row.created_at)
            for row in c360.exports
            if row.interview_id == interview.id
        ],
    )


@router.get("/candidates/{candidate_id}/360")
async def get_candidate_360(
    candidate_id: UUID, request: Request, principal: ViewsCandidates
) -> schemas.Candidate360Response:
    """The candidate's file for PRD §20's tabs: applications, screening, interview history with
    each evaluation, technical skills, proctoring counts, recordings, reports and notes. The
    resume and profile tabs are `GET /candidates/{id}`; the activity timeline is its own call."""
    async with own_tenant(request, principal) as session:
        scope = await resource_scope(session, principal.user_id)
        c360 = await load_candidate_360(session, candidate_id, scope, principal.permissions)
        jobs = {application.id: job for application, job in c360.detail.applications}
        authors = {note.author_id for note in c360.notes}
        people = (
            {
                user.id: user.name
                for user in await session.scalars(select(User).where(User.id.in_(authors)))
            }
            if authors
            else {}
        )
        sees_interviews = "reports.interview.view" in principal.permissions
        interviews = [_interview_item(data, c360, principal) for data in c360.interviews]
        resume = {skill.name.casefold(): skill for skill in c360.detail.skills}
        years = {
            skill.name.casefold(): float(skill.years)
            for skill in c360.detail.skills
            if skill.years is not None
        }
        ranks = {application.id: application.rank for application, _ in c360.detail.applications}
        taken: dict[str, list[schemas.SkillInterviewScore]] = {}
        for data in c360.interviews:
            if data.scores is None:
                continue
            for name, item in data.scores.skills.items():
                taken.setdefault(name, []).append(
                    schemas.SkillInterviewScore(
                        interview_id=data.interview.id,
                        reference=reference(data.interview.number),
                        score=item.value,
                    )
                )
        names = {skill.name for skill in c360.detail.skills} | set(taken)
        return schemas.Candidate360Response(
            candidate_id=candidate_id,
            name=c360.detail.candidate.name,
            access=schemas.TabAccess(
                interviews=sees_interviews,
                proctoring="reports.proctoring.view" in principal.permissions,
                recordings=sees_interviews,
                reports="reports.candidate.view" in principal.permissions,
                notes=True,
            ),
            applications=[
                schemas.ApplicationItem(
                    application_id=application.id,
                    job_id=job.id,
                    job_title=job.title,
                    stage=application.stage,
                    hiring_status=application.hiring_status,  # type: ignore[arg-type]
                    rank=application.rank,
                )
                for application, job in c360.detail.applications
            ],
            screening=[
                schemas.ScreeningItem(
                    application_id=result.application_id,
                    job_id=jobs[result.application_id].id,
                    job_title=jobs[result.application_id].title,
                    score=result.score,
                    rank=ranks.get(result.application_id),
                    strengths=list(result.strengths),
                    concerns=list(result.concerns),
                    missing=list(result.missing),
                    knockouts=list(result.knockouts),
                    screened_at=result.created_at,
                )
                for result in c360.screening
                if result.application_id in jobs
            ],
            interviews=interviews,
            skills=[
                schemas.SkillRow(
                    skill=name,
                    on_resume=name.casefold() in resume,
                    resume_years=years.get(name.casefold()),
                    interviews=taken.get(name, []),
                )
                for name in sorted(names, key=str.casefold)
            ],
            notes=[
                NoteResponse(
                    id=note.id,
                    candidate_id=note.candidate_id,
                    interview_id=note.interview_id,
                    author_id=note.author_id,
                    author_name=people.get(note.author_id, "A reviewer"),
                    body=note.body,
                    at_ms=note.at_ms,
                    created_at=note.created_at,
                )
                for note in c360.notes
            ],
        )


def _allowed_sources(principal: Principal) -> set[str]:
    allowed = {"screening", "recruiter"}
    if "reports.interview.view" in principal.permissions:
        allowed |= INTERVIEW_SOURCES
    if "reports.proctoring.view" in principal.permissions:
        allowed.add("proctoring")
    return allowed


@router.get("/candidates/{candidate_id}/timeline")
async def get_candidate_timeline(
    candidate_id: UUID,
    request: Request,
    principal: ViewsCandidates,
    source: Annotated[
        list[schemas.TimelineSource] | None,
        Query(description="Only these sources (PRD §98's eight); all the reader may see if empty."),
    ] = None,
    interview_id: Annotated[UUID | None, Query(description="Only this interview's.")] = None,
    before: Annotated[datetime | None, Query(description="Only older than this.")] = None,
    limit: Annotated[int, Query(ge=1, le=TIMELINE_LIMIT)] = 100,
) -> schemas.TimelineResponse:
    """What happened to the candidate, newest first, from screening, the interview, the
    transcript, coding, proctoring, recordings, the evaluation and the recruiters' own actions
    (PRD §98). A reader sees only the sources their permissions cover."""
    wanted = set(source) if source else set(SOURCES)
    sources = wanted & _allowed_sources(principal)
    async with own_tenant(request, principal) as session:
        scope = await resource_scope(session, principal.user_id)
        c360 = await load_candidate_360(session, candidate_id, scope, principal.permissions)
        interviews: list[Interview] = [data.interview for data in c360.interviews]
        if interview_id is not None:
            interviews = [i for i in interviews if i.id == interview_id]
        entries = await candidate_entries(
            session,
            candidate_id,
            c360.application_ids if interview_id is None else [],
            interviews,
            sources,
        )
    if interview_id is not None:
        entries = [entry for entry in entries if entry.interview_id == interview_id]
    if before is not None:
        entries = [entry for entry in entries if entry.at < before]
    entries.sort(key=lambda entry: entry.at, reverse=True)
    page = entries[:limit]
    return schemas.TimelineResponse(
        items=[schemas.TimelineItem(**entry.as_json()) for entry in page],
        next_before=page[-1].at if len(entries) > limit else None,
    )
