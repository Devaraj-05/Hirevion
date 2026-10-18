"""The unified timeline (PRD §98): what happened to a candidate, from eight sources in one order.

The sources are screening, interview, transcript, coding, proctoring, recording, evaluation and
recruiter actions. An entry that belongs to an interview carries its offset from the interview's
clock, which is what the review workspace seeks by. A reader sees only the sources their
permissions cover; the caller passes them in.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.models import (
    Application,
    ApplicationHistory,
    ApplicationStatusHistory,
    CandidateNote,
    HiringInput,
    Interview,
    Job,
    Report,
    ReportExport,
    ScreeningResult,
)
from hirevion_core.proctoring.catalogue import RANK
from hirevion_core.reports.data import InterviewData, user_names
from hirevion_core.reports.labels import (
    HIRING_LABELS,
    RECOMMENDATION_LABELS,
    REVIEW_LABELS,
    SEVERITY_LABELS,
    event_label,
)

STAGE_ACTIONS = {
    "shortlist": "Shortlisted",
    "reject": "Rejected",
    "hold": "Put on hold",
    "review": "Sent to recruiter review",
    "assign_recruiter": "Recruiter assigned",
    "assign_hiring_manager": "Hiring manager assigned",
}
REPORT_NAMES = {
    "interview": "Interview report",
    "proctoring": "Proctoring report",
    "coding": "Coding report",
    "candidate": "Candidate report",
    "candidate_visible": "Candidate-visible report",
}
SOURCES = (
    "screening",
    "interview",
    "transcript",
    "coding",
    "proctoring",
    "recording",
    "evaluation",
    "recruiter",
)
INTERVIEW_SOURCES = frozenset({"interview", "transcript", "coding", "evaluation", "recording"})
SCREENING_STAGES = ("uploaded", "parsed", "screened", "ranked")
TRACK_LABELS = {"mic": "Microphone", "camera": "Camera"}
DETAIL_MAX = 240
# An interview's closing events are written in the same moment as its end; anything later
# (the evaluation, a reviewer's note) happened after the interview, not inside it.
END_TOLERANCE_MS = 250


def allowed_sources(permissions: Collection[str]) -> frozenset[str]:
    """The sources a reader's permissions cover (PRD §98): the file's screening and the people's
    actions, the interview itself, and proctoring, each behind its own permission."""
    allowed: set[str] = set()
    if "candidates.view" in permissions or "reports.candidate.view" in permissions:
        allowed |= {"screening", "recruiter"}
    if "reports.interview.view" in permissions:
        allowed |= INTERVIEW_SOURCES
    if "reports.proctoring.view" in permissions:
        allowed.add("proctoring")
    return frozenset(allowed)


@dataclass(slots=True)
class Entry:
    at: datetime
    source: str
    kind: str
    title: str
    detail: str | None = None
    severity: str | None = None
    interview_id: UUID | None = None
    offset_ms: int | None = None
    actor: str | None = None
    ref: dict[str, Any] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        return {
            "at": self.at.isoformat(),
            "source": self.source,
            "kind": self.kind,
            "title": self.title,
            "detail": self.detail,
            "severity": self.severity,
            "interview_id": str(self.interview_id) if self.interview_id else None,
            "offset_ms": self.offset_ms,
            "actor": self.actor,
            "ref": self.ref,
        }


def _short(value: str) -> str:
    value = " ".join(value.split())
    return value if len(value) <= DETAIL_MAX else value[: DETAIL_MAX - 1] + "…"


def track_label(track: str) -> str:
    if track.startswith("screen-"):
        return f"Screen {track.removeprefix('screen-')}"
    if track.startswith("conversation-audio"):
        return "Conversation audio"
    if track.startswith("third-eye"):
        return "Third-eye camera"
    return TRACK_LABELS.get(track, track)


def _offset(data: InterviewData, at: datetime, ref: dict[str, Any] | None) -> int | None:
    """Where in the interview's clock an entry falls: a note says its own moment, and anything
    written after the interview ended (the evaluation, a decision) is not inside it."""
    if ref and isinstance(ref.get("at_ms"), int):
        return int(ref["at_ms"])
    offset = data.offset_ms(at)
    end = data.offset_ms(data.interview.ended_at)
    if offset is None or (end is not None and offset > end + END_TOLERANCE_MS):
        return None
    return offset


def interview_entries(
    data: InterviewData,
    sources: Collection[str],
    *,
    min_severity: str = "INFO",
    own_only: bool = False,
) -> list[Entry]:
    """The interview's entries, in the order they happened (unsorted across sources).

    `own_only` leaves out people's changes that belong to the application rather than to this
    interview (a candidate's timeline lists those once, from `application_entries`)."""
    interview = data.interview
    entries: list[Entry] = []

    def add(
        at: datetime | None,
        source: str,
        kind: str,
        title: str,
        detail: str | None = None,
        **more: Any,
    ) -> None:
        if at is None or source not in sources:
            return
        if kind == "proctor_review" and "proctoring" not in sources:
            return  # a review of a proctoring event shows what the event was
        entries.append(
            Entry(
                at=at,
                source=source,
                kind=kind,
                title=title,
                detail=_short(detail) if detail else None,
                interview_id=interview.id,
                offset_ms=_offset(data, at, more.get("ref")),
                **more,
            )
        )

    for step in data.lifecycle:
        add(
            step.created_at,
            "interview",
            step.action,
            f"Interview {step.action.replace('_', ' ')}",
            step.reason,
        )
    numbers = {question.id: question.position for question in data.questions}
    for question in data.questions:
        skill = f" ({question.skill})" if question.skill else ""
        add(
            question.asked_at,
            "transcript",
            "question",
            f"Question {question.position}{skill}",
            question.text,
            ref={"question_id": str(question.id)},
        )
        for answer in data.answers.get(question.id, []):
            add(
                answer.ended_at,
                "transcript",
                "answer",
                f"Answer to question {question.position}",
                answer.text,
                ref={"question_id": str(question.id)},
            )
    for snapshot in data.snapshots:
        add(
            snapshot.created_at,
            "coding",
            "snapshot",
            f"Code saved for question {numbers.get(snapshot.question_id, '?')}",
            f"{snapshot.language or 'text'}, {snapshot.size} characters",
            ref={"question_id": str(snapshot.question_id)},
        )
    floor = RANK.get(min_severity, 0)
    for event in data.events:
        if RANK.get(event.severity, 0) < floor:
            continue
        review = data.reviews.get(event.id)
        parts = [f"{SEVERITY_LABELS.get(event.severity, event.severity)}"]
        if event.duration_ms:
            parts.append(f"{round(event.duration_ms / 1000)} s")
        if review is not None:
            parts.append(REVIEW_LABELS[review.outcome])
        add(
            event.started_at,
            "proctoring",
            event.event.lower(),
            event_label(event.event),
            " · ".join(parts),
            severity=event.severity,
            ref={"event_id": str(event.id)},
        )
    for recording in data.recordings:
        label = track_label(recording.track)
        add(
            recording.assembled_at,
            "recording",
            "assembled",
            f"{label} recording ready",
            f"{round((recording.duration_ms or 0) / 1000)} s",
            ref={"track": recording.track},
        )
        for gap in recording.gaps:
            moment = gap.get("from_time")
            if isinstance(moment, str):
                add(
                    datetime.fromisoformat(moment),
                    "recording",
                    "gap",
                    f"{label} recording has a gap",
                    str(gap.get("kind") or gap.get("reason") or ""),
                    ref={"track": recording.track},
                )
    if data.evaluation is not None:
        overall = data.evaluation.overall_score
        add(
            data.evaluation.completed_at,
            "evaluation",
            "evaluated",
            "Evaluation completed",
            f"Overall {float(overall):.1f} of 10" if overall is not None else None,
            ref={"evaluation_id": str(data.evaluation.id)},
        )
    for note in data.notes:
        add(
            note.created_at,
            "recruiter",
            "note",
            "Note added",
            note.body,
            actor=data.person(note.author_id),
            ref={"note_id": str(note.id), "at_ms": note.at_ms},
        )
    for change in data.scores.changes if data.scores else []:
        was = f"{float(change.previous_score):.1f}" if change.previous_score is not None else "none"
        subject = change.target or change.scope
        add(
            change.created_at,
            "recruiter",
            "score_changed",
            f"Score changed: {subject}",
            f"{was} to {float(change.new_score):.1f}. {change.reason}",
            actor=data.person(change.changed_by),
        )
    for review in data.all_reviews:
        reviewed = next((row for row in data.events if row.id == review.proctor_event_id), None)
        add(
            review.created_at,
            "recruiter",
            "proctor_review",
            f"Proctor event reviewed: {event_label(reviewed.event) if reviewed else 'event'}",
            f"{REVIEW_LABELS[review.outcome]}. {review.reason}",
            actor=data.person(review.reviewer_id),
            ref={"event_id": str(review.proctor_event_id)},
        )
    for row in data.status_history:
        if row.source != "user":
            if row.interview_id == interview.id:
                add(
                    row.created_at,
                    "interview",
                    "hiring_status",
                    f"Hiring status: {HIRING_LABELS[row.to_status]}",
                )
            continue
        if row.interview_id != interview.id and (own_only or row.interview_id is not None):
            continue
        add(
            row.created_at,
            "recruiter",
            "decision" if row.decision else "hiring_status",
            ("Decision: " if row.decision else "Hiring status: ") + HIRING_LABELS[row.to_status],
            row.reason,
            actor=data.person(row.actor_id),
        )
    for given in data.hiring_inputs:
        if given.interview_id != interview.id and (own_only or given.interview_id is not None):
            continue
        add(
            given.created_at,
            "recruiter",
            "hiring_input",
            f"Hiring manager input: {RECOMMENDATION_LABELS[given.recommendation]}",
            given.rationale,
            actor=data.person(given.author_id),
        )
    return entries


async def application_entries(
    session: AsyncSession,
    candidate_id: UUID,
    application_ids: Sequence[UUID],
    sources: Collection[str],
) -> list[Entry]:
    """Entries about the candidate's applications that are not part of an interview: screening,
    stage changes, and notes taken on the candidate rather than on an interview."""
    entries: list[Entry] = []
    if not application_ids:
        return entries
    titles = {
        application_id: title
        for application_id, title in await session.execute(
            select(Application.id, Job.title)
            .join(Job, Job.id == Application.job_id)
            .where(Application.id.in_(application_ids))
        )
    }
    history = list(
        (
            await session.scalars(
                select(ApplicationHistory)
                .where(ApplicationHistory.application_id.in_(application_ids))
                .order_by(ApplicationHistory.created_at, ApplicationHistory.id)
            )
        ).all()
    )
    results = list(
        (
            await session.scalars(
                select(ScreeningResult)
                .where(ScreeningResult.application_id.in_(application_ids))
                .order_by(ScreeningResult.created_at)
            )
        ).all()
    )
    notes = list(
        (
            await session.scalars(
                select(CandidateNote)
                .where(
                    CandidateNote.candidate_id == candidate_id, CandidateNote.interview_id.is_(None)
                )
                .order_by(CandidateNote.created_at)
            )
        ).all()
    )
    status_rows = list(
        (
            await session.scalars(
                select(ApplicationStatusHistory)
                .where(
                    ApplicationStatusHistory.application_id.in_(application_ids),
                    ApplicationStatusHistory.interview_id.is_(None),
                    ApplicationStatusHistory.source == "user",
                    ApplicationStatusHistory.to_status == "additional_review",
                )
                .order_by(ApplicationStatusHistory.created_at)
            )
        ).all()
    )
    inputs = list(
        (
            await session.scalars(
                select(HiringInput)
                .where(
                    HiringInput.application_id.in_(application_ids),
                    HiringInput.interview_id.is_(None),
                )
                .order_by(HiringInput.created_at)
            )
        ).all()
    )
    exports = list(
        (
            await session.scalars(
                select(ReportExport)
                .where(ReportExport.audience == "internal")
                .where(
                    (ReportExport.candidate_id == candidate_id)
                    | ReportExport.interview_id.in_(
                        select(Interview.id).where(Interview.candidate_id == candidate_id)
                    )
                )
                .order_by(ReportExport.created_at)
            )
        ).all()
    )
    released = list(
        (
            await session.scalars(
                select(Report)
                .where(Report.application_id.in_(application_ids))
                .order_by(Report.created_at)
            )
        ).all()
    )
    user_ids = {
        *(row.actor_id for row in history if row.actor_id),
        *(note.author_id for note in notes),
        *(row.actor_id for row in status_rows if row.actor_id),
        *(row.author_id for row in inputs),
        *(row.requested_by for row in exports if row.requested_by),
        *(row.approved_by for row in released if row.approved_by),
        *(row.withdrawn_by for row in released if row.withdrawn_by),
    }
    people = await user_names(session, user_ids)

    def add(
        at: datetime | None,
        source: str,
        kind: str,
        title: str,
        detail: str | None = None,
        *,
        actor: UUID | None = None,
        interview_id: UUID | None = None,
        ref: dict[str, Any] | None = None,
    ) -> None:
        if at is None or source not in sources:
            return
        entries.append(
            Entry(
                at=at,
                source=source,
                kind=kind,
                title=title,
                detail=_short(detail) if detail else None,
                interview_id=interview_id,
                actor=people.get(actor, "A reviewer") if actor is not None else None,
                ref=ref or {},
            )
        )

    for result in results:
        add(
            result.created_at,
            "screening",
            "screened",
            f"Screened for {titles.get(result.application_id, 'a job')}",
            f"Match score {result.score} of 100",
            ref={"application_id": str(result.application_id)},
        )
    for row in history:
        job = titles.get(row.application_id, "a job")
        if row.to_stage in SCREENING_STAGES and row.actor_id is None:
            add(
                row.created_at,
                "screening",
                row.action,
                f"Resume {row.to_stage} for {job}",
                ref={"application_id": str(row.application_id)},
            )
        elif row.actor_id is not None:
            add(
                row.created_at,
                "recruiter",
                row.action,
                f"{STAGE_ACTIONS.get(row.action, row.action.replace('_', ' ').capitalize())}"
                f": {job}",
                row.reason,
                actor=row.actor_id,
                ref={"application_id": str(row.application_id)},
            )
    for note in notes:
        add(
            note.created_at,
            "recruiter",
            "note",
            "Note added",
            note.body,
            actor=note.author_id,
            ref={"note_id": str(note.id)},
        )
    for change in status_rows:
        add(
            change.created_at,
            "recruiter",
            "hiring_status",
            f"Hiring status: {HIRING_LABELS[change.to_status]}",
            change.reason,
            actor=change.actor_id,
        )
    for given in inputs:
        add(
            given.created_at,
            "recruiter",
            "hiring_input",
            f"Hiring manager input: {RECOMMENDATION_LABELS[given.recommendation]}",
            given.rationale,
            actor=given.author_id,
        )
    for export in exports:
        add(
            export.created_at,
            "recruiter",
            "report_exported",
            f"{REPORT_NAMES.get(export.kind, export.kind)} exported as a PDF",
            actor=export.requested_by,
            interview_id=export.interview_id,
        )
    for report in released:
        if report.approved_at is not None:
            add(
                report.approved_at,
                "recruiter",
                "report_released",
                "Candidate report released",
                actor=report.approved_by,
                interview_id=report.interview_id,
            )
        if report.withdrawn_at is not None:
            add(
                report.withdrawn_at,
                "recruiter",
                "report_withdrawn",
                "Candidate report withdrawn",
                report.withdrawn_reason,
                actor=report.withdrawn_by,
                interview_id=report.interview_id,
            )
    return entries


async def candidate_entries(
    session: AsyncSession,
    candidate_id: UUID,
    application_ids: Sequence[UUID],
    interviews: Sequence[InterviewData],
    sources: Collection[str],
    *,
    min_severity: str = "INFO",
) -> list[Entry]:
    """Every entry for the candidate within `sources`, oldest first. The interviews are already
    loaded (Candidate 360 holds them), so nothing is read twice."""
    entries = await application_entries(session, candidate_id, application_ids, sources)
    for data in interviews:
        entries += interview_entries(data, sources, min_severity=min_severity, own_only=True)
    return sorted(entries, key=lambda entry: entry.at)
