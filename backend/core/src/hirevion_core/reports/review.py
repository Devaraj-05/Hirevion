"""What the review workspace and the pipeline read (SP-17; PRD §71, §72): the media player's
tracks on one timeline, the queue of interviews waiting for a person, and the pipeline board.

The interview's clock is the shared one: transcript times, evidence times and every recording's
timeline map convert to and from it, so the player can seek all tracks from one position."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.scope import ResourceScope, job_scope_clause
from hirevion_core.hiring.workflow import FINISHED, allowed_targets
from hirevion_core.interviews.assignment import InterviewFilters, interviews_statement
from hirevion_core.models import (
    Application,
    Candidate,
    Evaluation,
    Interview,
    Job,
    ProctorEvent,
    Recording,
)
from hirevion_core.models.candidate import HIRING_STATUSES
from hirevion_core.recordings.playback import DownloadSigner, playable_tracks
from hirevion_core.recordings.segments import stored_blob
from hirevion_core.reports.data import InterviewData
from hirevion_core.reports.timeline import track_label
from hirevion_core.storage.service import StorageService

log = logging.getLogger(__name__)

AWAITING = ("interview_completed", "additional_review")
"""Hiring statuses of an application whose interview is done and that no one has decided yet."""
PER_COLUMN = 50
QUEUE_LIMIT = 100
MAP_MAX_BYTES = 1_000_000


def track_kind(track: str) -> str:
    if track.startswith("screen-"):
        return "screen"
    if track == "camera":
        return "camera"
    if track.startswith("third-eye"):
        return "third_eye"
    return "audio"


@dataclass(frozen=True, slots=True)
class MediaTrack:
    track: str
    kind: str
    label: str
    status: str
    stalled: bool
    url: str | None
    container: str | None
    duration_ms: int | None
    started_at: datetime | None
    timeline: dict[str, Any] | None
    gaps: list[dict[str, Any]]


async def _timeline_map(storage: StorageService, recording: Recording) -> dict[str, Any] | None:
    if not recording.timeline_path:
        return None
    try:
        raw = await storage.get(stored_blob(recording.organization_id, recording.timeline_path))
        if len(raw) > MAP_MAX_BYTES:
            return None
        loaded = json.loads(raw)
    except Exception as error:  # a missing or damaged map only costs the player its sync
        log.info("No timeline map for %s: %s", recording.track, error)
        return None
    return loaded if isinstance(loaded, dict) else None


async def review_media(
    session: AsyncSession,
    signer: DownloadSigner,
    storage: StorageService,
    data: InterviewData,
) -> list[MediaTrack]:
    """The interview's recorded tracks with short-lived read URLs and their timeline maps, in
    the order the player shows them. A track that isn't assembled yet has no URL."""
    interview = data.interview
    playable = await playable_tracks(session, signer, interview.organization_id, interview.id)
    by_track = {recording.track: recording for recording in data.recordings}
    result: list[MediaTrack] = []
    for item in sorted(playable, key=lambda t: (_kind_order(track_kind(t.track)), t.track)):
        recording = by_track.get(item.track)
        result.append(
            MediaTrack(
                track=item.track,
                kind=track_kind(item.track),
                label=track_label(item.track),
                status=item.status,
                stalled=item.stalled,
                url=item.file.url if item.file else None,
                container=item.file.container if item.file else None,
                duration_ms=item.file.duration_ms if item.file else None,
                started_at=recording.started_at if recording else None,
                timeline=await _timeline_map(storage, recording)
                if recording is not None and item.file is not None
                else None,
                gaps=item.gaps,
            )
        )
    return result


def _kind_order(kind: str) -> int:
    return {"camera": 0, "screen": 1, "third_eye": 2, "audio": 3}.get(kind, 9)


@dataclass(frozen=True, slots=True)
class PendingReview:
    interview: Interview
    candidate: Candidate
    job: Job
    hiring_status: str
    overall_score: float | None
    evaluated: bool
    unreviewed_critical: int


async def pending_reviews(
    session: AsyncSession,
    scope: ResourceScope,
    *,
    reviewer_only: UUID | None = None,
    limit: int = QUEUE_LIMIT,
) -> tuple[list[PendingReview], int]:
    """Interviews that have ended and wait for a person to decide, oldest first, and how many
    there are in all."""
    base = (
        interviews_statement(scope, InterviewFilters(), reviewer_only=reviewer_only)
        .join(Application, Application.id == Interview.application_id)
        .where(Interview.status.in_(FINISHED), Application.hiring_status.in_(AWAITING))
    )
    total = int(
        await session.scalar(select(func.count()).select_from(base.order_by(None).subquery())) or 0
    )
    rows = await session.execute(
        base.add_columns(Candidate, Job, Application.hiring_status)
        .join(Candidate, Candidate.id == Interview.candidate_id)
        .join(Job, Job.id == Interview.job_id)
        .order_by(Interview.completed_at.asc().nulls_last(), Interview.id)
        .limit(limit)
    )
    found = [(row[0], row[1], row[2], row[3]) for row in rows]
    ids = [interview.id for interview, *_ in found]
    scores: dict[UUID, float | None] = {}
    critical: dict[UUID, int] = {}
    if ids:
        for interview_id, overall in await session.execute(
            select(Evaluation.interview_id, Evaluation.overall_score).where(
                Evaluation.interview_id.in_(ids),
                Evaluation.kind == "initial",
                Evaluation.status == "ready",
            )
        ):
            scores[interview_id] = float(overall) if overall is not None else None
        for interview_id, count in await session.execute(
            select(ProctorEvent.interview_id, func.count())
            .where(
                ProctorEvent.interview_id.in_(ids),
                ProctorEvent.severity == "CRITICAL",
                ProctorEvent.review_status == "pending",
            )
            .group_by(ProctorEvent.interview_id)
        ):
            critical[interview_id] = count
    return (
        [
            PendingReview(
                interview=interview,
                candidate=candidate,
                job=job,
                hiring_status=status,
                overall_score=scores.get(interview.id),
                evaluated=interview.id in scores,
                unreviewed_critical=critical.get(interview.id, 0),
            )
            for interview, candidate, job, status in found
        ],
        total,
    )


async def pending_count(
    session: AsyncSession, scope: ResourceScope, *, reviewer_only: UUID | None = None
) -> int:
    base = (
        interviews_statement(scope, InterviewFilters(), reviewer_only=reviewer_only)
        .join(Application, Application.id == Interview.application_id)
        .where(Interview.status.in_(FINISHED), Application.hiring_status.in_(AWAITING))
    )
    return int(
        await session.scalar(select(func.count()).select_from(base.order_by(None).subquery())) or 0
    )


@dataclass(frozen=True, slots=True)
class Card:
    application_id: UUID
    candidate_id: UUID
    candidate_name: str
    job_id: UUID
    job_title: str
    hiring_status: str
    interview_id: UUID | None
    moves: list[str]


@dataclass(frozen=True, slots=True)
class Column:
    status: str
    count: int
    cards: list[Card]


async def pipeline(
    session: AsyncSession,
    scope: ResourceScope,
    *,
    can_manage: bool,
    can_decide: bool,
    job_id: UUID | None = None,
    per_column: int = PER_COLUMN,
) -> list[Column]:
    """The nine statuses with their counts and newest cards (PRD §72), within `scope`."""
    where = [job_scope_clause(scope)]
    if job_id is not None:
        where.append(Application.job_id == job_id)
    counts = dict(
        (str(status), int(count))
        for status, count in await session.execute(
            select(Application.hiring_status, func.count())
            .join(Job, Job.id == Application.job_id)
            .where(*where)
            .group_by(Application.hiring_status)
        )
    )
    columns: list[Column] = []
    for status in HIRING_STATUSES:
        rows = await session.execute(
            select(Application, Candidate, Job)
            .join(Candidate, Candidate.id == Application.candidate_id)
            .join(Job, Job.id == Application.job_id)
            .where(*where, Application.hiring_status == status)
            .order_by(Application.updated_at.desc(), Application.id.desc())
            .limit(per_column)
        )
        found = [(row[0], row[1], row[2]) for row in rows]
        # The card links to the newest finished interview (what there is to review), else the
        # newest; a move that needs a finished interview checks the same one `change_status` does.
        newest: dict[UUID, UUID] = {}
        finished: dict[UUID, UUID] = {}
        if found:
            for application_id, interview_id, interview_status in await session.execute(
                select(Interview.application_id, Interview.id, Interview.status)
                .where(Interview.application_id.in_([a.id for a, *_ in found]))
                .order_by(Interview.created_at)
            ):
                newest[application_id] = interview_id
                if interview_status in FINISHED:
                    finished[application_id] = interview_id
        columns.append(
            Column(
                status=status,
                count=counts.get(status, 0),
                cards=[
                    Card(
                        application_id=application.id,
                        candidate_id=candidate.id,
                        candidate_name=candidate.name,
                        job_id=job.id,
                        job_title=job.title,
                        hiring_status=status,
                        interview_id=finished.get(application.id) or newest.get(application.id),
                        moves=allowed_targets(
                            status,
                            can_decide=can_decide,
                            has_interview=application.id in finished,
                            can_manage=can_manage,
                        ),
                    )
                    for application, candidate, job in found
                ],
            )
        )
    return columns


__all__ = [
    "AWAITING",
    "Card",
    "Column",
    "MediaTrack",
    "PendingReview",
    "pending_count",
    "pending_reviews",
    "pipeline",
    "review_media",
]
