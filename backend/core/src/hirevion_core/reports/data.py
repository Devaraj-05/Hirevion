"""Everything the reports and the review workspace read about one interview, loaded once.

Reports are built from this and nothing else, so what a reader may see is decided here: the
caller passes an interview it already checked against the reader's scope, and each report builder
leaves out what its reader's permissions don't cover."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.hiring import inputs, scores
from hirevion_core.hiring.scores import ScoreView
from hirevion_core.interview_session.transcripts import segments as load_segments
from hirevion_core.models import (
    Application,
    ApplicationStatusHistory,
    Candidate,
    CandidateNote,
    Evaluation,
    HiringInput,
    Interview,
    InterviewAnswer,
    InterviewEvent,
    InterviewQuestion,
    InterviewSession,
    InterviewTemplateVersion,
    Job,
    ProctorEvent,
    ProctorEventReview,
    ProctorEvidence,
    ProctorSession,
    QuestionEvaluation,
    Recording,
    SystemCheckResult,
    TranscriptSegment,
    User,
    WorkspaceSnapshot,
)


@dataclass(slots=True)
class InterviewData:
    interview: Interview
    candidate: Candidate
    job: Job
    application: Application
    template_name: str
    run: InterviewSession | None
    questions: list[InterviewQuestion]
    answers: dict[UUID, list[InterviewAnswer]]
    segments: list[TranscriptSegment]
    evaluation: Evaluation | None
    question_evaluations: dict[UUID, QuestionEvaluation]
    scores: ScoreView | None
    system_check: SystemCheckResult | None
    proctor: ProctorSession | None
    events: list[ProctorEvent]
    reviews: dict[UUID, ProctorEventReview]
    """The latest review of each reviewed event."""
    all_reviews: list[ProctorEventReview]
    evidence: list[ProctorEvidence]
    recordings: list[Recording]
    snapshots: list[WorkspaceSnapshot]
    notes: list[CandidateNote]
    """Notes about this interview, oldest first."""
    status_history: list[ApplicationStatusHistory]
    lifecycle: list[InterviewEvent]
    """The interview's own history: invited, started, interrupted, completed, evaluated."""
    hiring_inputs: list[HiringInput]
    people: dict[UUID, str] = field(default_factory=dict)
    """Names of the users who appear in the data."""

    @property
    def anchor(self) -> datetime | None:
        """When the interview's clock started: transcript and evidence times count from here."""
        if self.run is not None:
            return self.run.started_at
        return self.interview.started_at

    @property
    def timezone(self) -> str:
        return self.interview.timezone

    def offset_ms(self, moment: datetime | None) -> int | None:
        anchor = self.anchor
        if moment is None or anchor is None:
            return None
        return int((moment - anchor).total_seconds() * 1000)

    def person(self, user_id: UUID | None) -> str:
        return self.people.get(user_id, "A reviewer") if user_id is not None else "The system"


async def user_names(session: AsyncSession, user_ids: Iterable[UUID | None]) -> dict[UUID, str]:
    """Names of the users whose ids are given (the organisation's rows are all the session sees)."""
    wanted = {user_id for user_id in user_ids if user_id is not None}
    if not wanted:
        return {}
    rows = await session.execute(select(User.id, User.name).where(User.id.in_(wanted)))
    return {user_id: name for user_id, name in rows}


async def load_interview_data(
    session: AsyncSession, interview: Interview, *, with_transcript: bool = True
) -> InterviewData:
    """`with_transcript=False` leaves out the transcript's segments, for readers that don't need
    them (the timeline), since they are the bulk of the data."""
    candidate = await session.get_one(Candidate, interview.candidate_id)
    job = await session.get_one(Job, interview.job_id)
    application = await session.get_one(Application, interview.application_id)
    template_name = (
        await session.scalar(
            select(InterviewTemplateVersion.name).where(
                InterviewTemplateVersion.template_id == interview.template_id,
                InterviewTemplateVersion.version == interview.template_version,
            )
        )
        or ""
    )
    run = await session.get(InterviewSession, interview.id)
    questions = list(
        (
            await session.scalars(
                select(InterviewQuestion)
                .where(InterviewQuestion.interview_id == interview.id)
                .order_by(InterviewQuestion.position)
            )
        ).all()
    )
    answers: dict[UUID, list[InterviewAnswer]] = {}
    for answer in await session.scalars(
        select(InterviewAnswer)
        .where(InterviewAnswer.interview_id == interview.id)
        .order_by(InterviewAnswer.created_at, InterviewAnswer.id)
    ):
        answers.setdefault(answer.question_id, []).append(answer)
    evaluation = await scores.latest_evaluation(session, interview.id)
    question_evaluations: dict[UUID, QuestionEvaluation] = {}
    score_view: ScoreView | None = None
    if evaluation is not None:
        for row in await session.scalars(
            select(QuestionEvaluation).where(QuestionEvaluation.evaluation_id == evaluation.id)
        ):
            question_evaluations[row.question_id] = row
        score_view = await scores.score_view(
            session, interview, evaluation=evaluation, question_evaluations=question_evaluations
        )
    proctor = await session.scalar(
        select(ProctorSession).where(ProctorSession.interview_id == interview.id)
    )
    events = list(
        (
            await session.scalars(
                select(ProctorEvent)
                .where(ProctorEvent.interview_id == interview.id)
                .order_by(ProctorEvent.started_at, ProctorEvent.id)
            )
        ).all()
    )
    reviews_all: list[ProctorEventReview] = []
    if events:
        reviews_all = list(
            (
                await session.scalars(
                    select(ProctorEventReview)
                    .where(ProctorEventReview.proctor_event_id.in_([event.id for event in events]))
                    .order_by(ProctorEventReview.created_at, ProctorEventReview.id)
                )
            ).all()
        )
    latest_review = {review.proctor_event_id: review for review in reviews_all}
    notes = list(
        (
            await session.scalars(
                select(CandidateNote)
                .where(CandidateNote.interview_id == interview.id)
                .order_by(CandidateNote.created_at, CandidateNote.id)
            )
        ).all()
    )
    history = list(
        (
            await session.scalars(
                select(ApplicationStatusHistory)
                .where(ApplicationStatusHistory.application_id == application.id)
                .order_by(ApplicationStatusHistory.created_at, ApplicationStatusHistory.id)
            )
        ).all()
    )
    current_inputs = await inputs.current_inputs(session, application.id)
    user_ids: set[UUID] = {
        *(review.reviewer_id for review in reviews_all),
        *(note.author_id for note in notes),
        *(row.actor_id for row in history if row.actor_id is not None),
        *(row.author_id for row in current_inputs),
        *(change.changed_by for change in (score_view.changes if score_view else [])),
    }
    people = await user_names(session, user_ids)
    return InterviewData(
        interview=interview,
        candidate=candidate,
        job=job,
        application=application,
        template_name=template_name,
        run=run,
        questions=questions,
        answers=answers,
        segments=await load_segments(session, interview.id) if with_transcript else [],
        evaluation=evaluation,
        question_evaluations=question_evaluations,
        scores=score_view,
        system_check=await session.scalar(
            select(SystemCheckResult)
            .where(SystemCheckResult.interview_id == interview.id)
            .order_by(SystemCheckResult.created_at.desc())
            .limit(1)
        ),
        proctor=proctor,
        events=events,
        reviews=latest_review,
        all_reviews=reviews_all,
        evidence=list(
            (
                await session.scalars(
                    select(ProctorEvidence)
                    .where(ProctorEvidence.interview_id == interview.id)
                    .order_by(ProctorEvidence.created_at, ProctorEvidence.id)
                )
            ).all()
        ),
        recordings=list(
            (
                await session.scalars(
                    select(Recording)
                    .where(Recording.interview_id == interview.id)
                    .order_by(Recording.track)
                )
            ).all()
        ),
        snapshots=list(
            (
                await session.scalars(
                    select(WorkspaceSnapshot)
                    .where(WorkspaceSnapshot.interview_id == interview.id)
                    .order_by(WorkspaceSnapshot.created_at, WorkspaceSnapshot.id)
                )
            ).all()
        ),
        notes=notes,
        status_history=history,
        lifecycle=list(
            (
                await session.scalars(
                    select(InterviewEvent)
                    .where(InterviewEvent.interview_id == interview.id)
                    .order_by(InterviewEvent.created_at, InterviewEvent.id)
                )
            ).all()
        ),
        hiring_inputs=current_inputs,
        people=people,
    )
