"""The review workspace and the hiring workflow (SP-17; PRD §71, §72): the player's media on one
timeline, notes, score changes with a reason, Hiring Manager input, the hiring status and the
final decision, the queue of interviews waiting for a person, and the pipeline board.

Every route reaches only what the caller's resource scope reaches. Playing media is audited as
`recording.viewed`, a score change as `score.modified`, and every status change (a decision
included) in the audit log and the application's status history."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_api.access.deps import own_tenant, scoped_interview
from hirevion_api.authz import Principal, requires
from hirevion_api.deps import get_storage
from hirevion_api.review import schemas
from hirevion_api.routing import api_router
from hirevion_core.access.audit import record
from hirevion_core.access.errors import NotFound
from hirevion_core.access.scope import ResourceScope, resource_scope, scope_clause
from hirevion_core.candidates.candidates import get_candidate
from hirevion_core.hiring import inputs, notes, scores, workflow
from hirevion_core.interviews.lifecycle import reference
from hirevion_core.models import (
    Application,
    ApplicationStatusHistory,
    CandidateNote,
    HiringInput,
    Interview,
    Job,
    ScoreChange,
)
from hirevion_core.recordings.playback import DownloadSigner, url_lifetime
from hirevion_core.reports import review
from hirevion_core.reports.data import load_interview_data, user_names
from hirevion_core.storage.service import StorageService

router = api_router(tags=["review"])

ReadsInterviews = Annotated[Principal, requires("reports.interview.view")]
ViewsCandidates = Annotated[Principal, requires("candidates.view")]
ManagesCandidates = Annotated[Principal, requires("candidates.manage")]
ModifiesScores = Annotated[Principal, requires("reports.score.modify")]
GivesInput = Annotated[Principal, requires("hiring.input")]


async def _application(
    session: AsyncSession, principal: Principal, application_id: UUID
) -> tuple[Application, Job]:
    scope = await resource_scope(session, principal.user_id)
    row = (
        await session.execute(
            select(Application, Job)
            .join(Job, Job.id == Application.job_id)
            .where(
                Application.id == application_id,
                scope_clause(scope, team_column=Job.team_id, owner_column=Job.recruiter_id),
            )
        )
    ).first()
    if row is None:
        raise NotFound("application-not-found", "No such application")
    return row[0], row[1]


# The player.


@router.get("/interviews/{interview_id}/review/media")
async def get_review_media(
    interview_id: UUID, request: Request, principal: ReadsInterviews
) -> schemas.ReviewMediaResponse:
    """Every recorded track (camera, screen, third eye, audio) with a five-minute read URL and
    its timeline map, so the player can seek them all from one position. Playing recordings is
    audited as `recording.viewed`."""
    storage = get_storage(request)
    issued = datetime.now(UTC)
    async with own_tenant(request, principal) as session:
        interview = await scoped_interview(session, principal, interview_id)
        data = await load_interview_data(session, interview, with_transcript=False)
        found = await review.review_media(
            session,
            cast(DownloadSigner, storage),
            cast(StorageService, storage),
            data,
        )
        await record(
            session,
            principal.actor(request),
            "recording.viewed",
            "interview",
            interview.id,
            details={
                "via": "review",
                "tracks": [t.track for t in found],
                "files": sum(1 for t in found if t.url is not None),
            },
        )
    return schemas.ReviewMediaResponse(
        interview_id=interview_id,
        anchor=data.anchor,
        expires_at=issued + url_lifetime(),
        tracks=[
            schemas.MediaTrackResponse(
                track=t.track,
                kind=t.kind,  # type: ignore[arg-type]
                label=t.label,
                status=t.status,
                stalled=t.stalled,
                url=t.url,
                container=t.container,
                duration_ms=t.duration_ms,
                started_at=t.started_at,
                timeline=t.timeline,
                gaps=t.gaps,
            )
            for t in found
        ],
    )


# Notes.


def _note(row: CandidateNote, people: dict[UUID, str]) -> schemas.NoteResponse:
    return schemas.NoteResponse(
        id=row.id,
        candidate_id=row.candidate_id,
        interview_id=row.interview_id,
        author_id=row.author_id,
        author_name=people.get(row.author_id, "A reviewer"),
        body=row.body,
        at_ms=row.at_ms,
        created_at=row.created_at,
    )


@router.get("/interviews/{interview_id}/notes")
async def list_interview_notes(
    interview_id: UUID, request: Request, principal: ReadsInterviews
) -> schemas.NoteList:
    """The notes taken on this interview, newest first."""
    async with own_tenant(request, principal) as session:
        interview = await scoped_interview(session, principal, interview_id)
        rows = await notes.list_notes(session, interview.candidate_id, interview_id=interview.id)
        people = await user_names(session, {row.author_id for row in rows})
    return schemas.NoteList(items=[_note(row, people) for row in rows])


@router.post("/interviews/{interview_id}/notes", status_code=201)
async def add_interview_note(
    interview_id: UUID, body: schemas.NoteBody, request: Request, principal: ReadsInterviews
) -> schemas.NoteResponse:
    """Adds a note to the interview, optionally at a moment of it (milliseconds from its start)."""
    async with own_tenant(request, principal) as session:
        interview = await scoped_interview(session, principal, interview_id)
        row = await notes.add_note(
            session,
            principal.actor(request),
            candidate_id=interview.candidate_id,
            interview=interview,
            body=body.body,
            at_ms=body.at_ms,
        )
        people = await user_names(session, {row.author_id})
    return _note(row, people)


@router.get("/candidates/{candidate_id}/notes")
async def list_candidate_notes(
    candidate_id: UUID, request: Request, principal: ViewsCandidates
) -> schemas.NoteList:
    """Every note on the candidate, newest first."""
    async with own_tenant(request, principal) as session:
        scope = await resource_scope(session, principal.user_id)
        await get_candidate(session, candidate_id, scope)
        rows = await notes.list_notes(session, candidate_id)
        people = await user_names(session, {row.author_id for row in rows})
    return schemas.NoteList(items=[_note(row, people) for row in rows])


@router.post("/candidates/{candidate_id}/notes", status_code=201)
async def add_candidate_note(
    candidate_id: UUID, body: schemas.NoteBody, request: Request, principal: ViewsCandidates
) -> schemas.NoteResponse:
    async with own_tenant(request, principal) as session:
        scope = await resource_scope(session, principal.user_id)
        await get_candidate(session, candidate_id, scope)
        row = await notes.add_note(
            session, principal.actor(request), candidate_id=candidate_id, body=body.body
        )
        people = await user_names(session, {row.author_id})
    return _note(row, people)


# Scores.


def _change(row: ScoreChange, people: dict[UUID, str]) -> schemas.ScoreChangeResponse:
    return schemas.ScoreChangeResponse(
        id=row.id,
        scope=row.scope,  # type: ignore[arg-type]
        target=row.target,
        previous_score=float(row.previous_score) if row.previous_score is not None else None,
        new_score=float(row.new_score),
        reason=row.reason,
        changed_by=row.changed_by,
        changed_by_name=people.get(row.changed_by, "A reviewer"),
        created_at=row.created_at,
    )


def _value(item: scores.ScoreValue, people: dict[UUID, str]) -> schemas.ScoreValueResponse:
    return schemas.ScoreValueResponse(
        ai=item.ai,
        value=item.value,
        change=_change(item.change, people) if item.change is not None else None,
    )


async def _scores(session: AsyncSession, interview: Interview) -> schemas.ScoresResponse:
    view = await scores.score_view(session, interview)
    people = await user_names(session, {change.changed_by for change in view.changes})
    return schemas.ScoresResponse(
        interview_id=interview.id,
        evaluation_id=view.evaluation_id,
        overall=_value(view.overall, people),
        communication=_value(view.communication, people),
        skills={name: _value(item, people) for name, item in view.skills.items()},
        questions={key: _value(item, people) for key, item in view.questions.items()},
        changes=[_change(change, people) for change in view.changes],
    )


@router.get("/interviews/{interview_id}/scores")
async def get_scores(
    interview_id: UUID, request: Request, principal: ReadsInterviews
) -> schemas.ScoresResponse:
    """The evaluation's scores with the people's changes laid over the AI's, and every change
    with its reason."""
    async with own_tenant(request, principal) as session:
        interview = await scoped_interview(session, principal, interview_id)
        return await _scores(session, interview)


@router.post("/interviews/{interview_id}/score-changes", status_code=201)
async def change_score(
    interview_id: UUID, body: schemas.ScoreChangeBody, request: Request, principal: ModifiesScores
) -> schemas.ScoresResponse:
    """Changes one score, with the reason. The AI's score stays on record; the change is
    audited as `score.modified`."""
    async with own_tenant(request, principal) as session:
        interview = await scoped_interview(session, principal, interview_id)
        await scores.change_score(
            session,
            principal.actor(request),
            interview,
            body.scope,
            body.target,
            body.new_score,
            body.reason,
        )
        return await _scores(session, interview)


# The hiring workflow.


def _history(row: ApplicationStatusHistory, people: dict[UUID, str]) -> schemas.HistoryItem:
    return schemas.HistoryItem(
        id=row.id,
        from_status=row.from_status,  # type: ignore[arg-type]
        to_status=row.to_status,  # type: ignore[arg-type]
        source=row.source,  # type: ignore[arg-type]
        decision=row.decision,
        reason=row.reason,
        actor_id=row.actor_id,
        actor_name=people.get(row.actor_id) if row.actor_id else None,
        interview_id=row.interview_id,
        created_at=row.created_at,
    )


def _input(row: HiringInput, people: dict[UUID, str]) -> schemas.HiringInputResponse:
    return schemas.HiringInputResponse(
        id=row.id,
        author_id=row.author_id,
        author_name=people.get(row.author_id, "A hiring manager"),
        interview_id=row.interview_id,
        recommendation=row.recommendation,  # type: ignore[arg-type]
        ratings={k: int(v) for k, v in row.ratings.items()},
        rationale=row.rationale,
        created_at=row.created_at,
    )


async def _hiring_state(
    session: AsyncSession, principal: Principal, application: Application, job: Job
) -> schemas.HiringStateResponse:
    finished = await workflow.finished_interview(session, application.id)
    rows = list(
        (
            await session.scalars(
                select(ApplicationStatusHistory)
                .where(ApplicationStatusHistory.application_id == application.id)
                .order_by(
                    ApplicationStatusHistory.created_at.desc(),
                    ApplicationStatusHistory.id.desc(),
                )
            )
        ).all()
    )
    given = await inputs.current_inputs(session, application.id)
    people = await user_names(
        session,
        {*(row.actor_id for row in rows), *(row.author_id for row in given)},
    )
    decision = next(
        (row for row in rows if row.decision and row.to_status == application.hiring_status),
        None,
    )
    return schemas.HiringStateResponse(
        application_id=application.id,
        candidate_id=application.candidate_id,
        job_id=job.id,
        job_title=job.title,
        status=application.hiring_status,  # type: ignore[arg-type]
        allowed=workflow.allowed_targets(  # type: ignore[arg-type]
            application.hiring_status,
            can_decide="hiring.decide" in principal.permissions,
            has_interview=finished is not None,
            can_manage="candidates.manage" in principal.permissions,
        ),
        has_interview=finished is not None,
        decision=_history(decision, people) if decision is not None else None,
        history=[_history(row, people) for row in rows],
        inputs=[_input(row, people) for row in given],
    )


@router.get("/applications/{application_id}/hiring")
async def get_hiring_state(
    application_id: UUID, request: Request, principal: ViewsCandidates
) -> schemas.HiringStateResponse:
    """Where the hiring stands (PRD §72): the status, what may be chosen next, the history of
    every change, the final decision and the Hiring Managers' input."""
    async with own_tenant(request, principal) as session:
        application, job = await _application(session, principal, application_id)
        return await _hiring_state(session, principal, application, job)


@router.post("/applications/{application_id}/hiring-status")
async def change_hiring_status(
    application_id: UUID,
    body: schemas.HiringStatusBody,
    request: Request,
    principal: ManagesCandidates,
) -> schemas.HiringStateResponse:
    """Moves the application to another status, with a reason where one is needed. `selected`
    and a rejection after an interview are the final decision and need `hiring.decide`; the
    interview's own statuses can't be chosen. Every change is audited."""
    async with own_tenant(request, principal) as session:
        application, job = await _application(session, principal, application_id)
        await workflow.change_status(
            session, principal.actor(request), application.id, body.status, reason=body.reason
        )
        await session.refresh(application)
        return await _hiring_state(session, principal, application, job)


@router.post("/applications/{application_id}/hiring-inputs", status_code=201)
async def add_hiring_input(
    application_id: UUID,
    body: schemas.HiringInputBody,
    request: Request,
    principal: GivesInput,
) -> schemas.HiringInputResponse:
    """A Hiring Manager's recommendation with the reasons. It informs the decision and never
    moves the status."""
    async with own_tenant(request, principal) as session:
        application, _ = await _application(session, principal, application_id)
        row = await inputs.add_input(
            session,
            principal.actor(request),
            application,
            recommendation=body.recommendation,
            ratings=body.ratings,
            rationale=body.rationale,
        )
        people = await user_names(session, {row.author_id})
    return _input(row, people)


# The queue and the pipeline.


@router.get("/reviews/pending")
async def list_pending_reviews(
    request: Request, principal: ReadsInterviews
) -> schemas.PendingReviewList:
    """Interviews that have ended and wait for a person to decide, longest waiting first."""
    async with own_tenant(request, principal) as session:
        scope = await resource_scope(session, principal.user_id)
        found, total = await review.pending_reviews(
            session, scope, reviewer_only=principal.reviewer_only
        )
        applications = {item.interview.id: item.interview.application_id for item in found}
    return schemas.PendingReviewList(
        total=total,
        items=[
            schemas.PendingReviewItem(
                interview_id=item.interview.id,
                reference=reference(item.interview.number),
                application_id=applications[item.interview.id],
                candidate_id=item.candidate.id,
                candidate_name=item.candidate.name,
                job_title=item.job.title,
                hiring_status=item.hiring_status,  # type: ignore[arg-type]
                completed_at=item.interview.completed_at,
                overall_score=item.overall_score,
                evaluated=item.evaluated,
                unreviewed_critical=item.unreviewed_critical,
            )
            for item in found
        ],
    )


@router.get("/pipeline")
async def get_pipeline(
    request: Request, principal: ViewsCandidates, job: UUID | None = None
) -> schemas.PipelineResponse:
    """The hiring pipeline (PRD §72): the nine statuses with their counts and newest cards, and
    for each card the moves this reader may make."""
    async with own_tenant(request, principal) as session:
        scope: ResourceScope = await resource_scope(session, principal.user_id)
        columns = await review.pipeline(
            session,
            scope,
            can_manage="candidates.manage" in principal.permissions,
            can_decide="hiring.decide" in principal.permissions,
            job_id=job,
        )
    return schemas.PipelineResponse(
        columns=[
            schemas.PipelineColumn(
                status=column.status,  # type: ignore[arg-type]
                count=column.count,
                cards=[
                    schemas.PipelineCard(
                        application_id=card.application_id,
                        candidate_id=card.candidate_id,
                        candidate_name=card.candidate_name,
                        job_id=card.job_id,
                        job_title=card.job_title,
                        interview_id=card.interview_id,
                        moves=card.moves,  # type: ignore[arg-type]
                    )
                    for card in column.cards
                ],
            )
            for column in columns
        ]
    )
