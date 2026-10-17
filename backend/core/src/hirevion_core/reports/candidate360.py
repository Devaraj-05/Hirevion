"""Candidate 360 (PRD §19, §20): one candidate's whole file, loaded within the reader's scope.

The API shows it tab by tab and the internal candidate report prints it, so both read this. What a
reader may not see is left out here (their permissions decide which parts load), never hidden
later."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.scope import ResourceScope
from hirevion_core.candidates.candidates import CandidateDetail, get_candidate
from hirevion_core.hiring import inputs
from hirevion_core.interviews.assignment import InterviewFilters, interviews_statement
from hirevion_core.models import (
    ApplicationStatusHistory,
    CandidateNote,
    HiringInput,
    Interview,
    Report,
    ReportExport,
    ScreeningResult,
    User,
)
from hirevion_core.reports.data import InterviewData, load_interview_data


@dataclass(slots=True)
class Candidate360:
    detail: CandidateDetail
    screening: list[ScreeningResult]
    """The latest result of each application."""
    interviews: list[InterviewData]
    """Newest first; empty when the reader may not see interviews."""
    notes: list[CandidateNote]
    exports: list[ReportExport]
    candidate_reports: dict[UUID, Report]
    """The candidate-visible report of each interview that has one."""
    hiring_inputs: dict[UUID, list[HiringInput]]
    """By application: the latest of each author."""
    history: dict[UUID, list[ApplicationStatusHistory]]
    people: dict[UUID, str] = field(default_factory=dict)

    @property
    def application_ids(self) -> list[UUID]:
        return [application.id for application, _ in self.detail.applications]


async def load_candidate_360(
    session: AsyncSession,
    candidate_id: UUID,
    scope: ResourceScope,
    permissions: Collection[str],
) -> Candidate360:
    """The candidate, if `scope` reaches them. Interviews, notes and reports load only for a
    reader who holds the permission to see them."""
    detail = await get_candidate(session, candidate_id, scope)
    application_ids = [application.id for application, _ in detail.applications]
    screening: list[ScreeningResult] = []
    seen: set[UUID] = set()
    for result in await session.scalars(
        select(ScreeningResult)
        .where(ScreeningResult.application_id.in_(application_ids or [None]))
        .order_by(ScreeningResult.created_at.desc())
    ):
        if result.application_id not in seen:
            seen.add(result.application_id)
            screening.append(result)
    interview_data: list[InterviewData] = []
    if "reports.interview.view" in permissions:
        rows = await session.scalars(
            interviews_statement(scope, InterviewFilters(candidate_id=candidate_id))
            .where(Interview.application_id.in_(application_ids or [None]))
            .order_by(Interview.created_at.desc(), Interview.id.desc())
        )
        for interview in rows.all():
            interview_data.append(
                await load_interview_data(session, interview, with_transcript=False)
            )
    notes = list(
        (
            await session.scalars(
                select(CandidateNote)
                .where(CandidateNote.candidate_id == candidate_id)
                .order_by(CandidateNote.created_at.desc(), CandidateNote.id.desc())
                .limit(200)
            )
        ).all()
    )
    interview_ids = [data.interview.id for data in interview_data]
    exports: list[ReportExport] = []
    reports: dict[UUID, Report] = {}
    if interview_ids:
        exports = list(
            (
                await session.scalars(
                    select(ReportExport)
                    .where(
                        ReportExport.audience == "internal",
                        ReportExport.interview_id.in_(interview_ids),
                    )
                    .order_by(ReportExport.created_at.desc())
                )
            ).all()
        )
        reports = {
            report.interview_id: report
            for report in await session.scalars(
                select(Report).where(Report.interview_id.in_(interview_ids))
            )
        }
    given: dict[UUID, list[HiringInput]] = {}
    history: dict[UUID, list[ApplicationStatusHistory]] = {}
    for application_id in application_ids:
        given[application_id] = await inputs.current_inputs(session, application_id)
    if application_ids:
        for row in await session.scalars(
            select(ApplicationStatusHistory)
            .where(ApplicationStatusHistory.application_id.in_(application_ids))
            .order_by(
                ApplicationStatusHistory.created_at.desc(), ApplicationStatusHistory.id.desc()
            )
        ):
            history.setdefault(row.application_id, []).append(row)
    user_ids = {
        *(note.author_id for note in notes),
        *(row.author_id for rows in given.values() for row in rows),
        *(row.actor_id for rows in history.values() for row in rows if row.actor_id),
        *(row.requested_by for row in exports if row.requested_by),
    }
    people = (
        {
            user.id: user.name
            for user in await session.scalars(select(User).where(User.id.in_(user_ids)))
        }
        if user_ids
        else {}
    )
    return Candidate360(
        detail=detail,
        screening=screening,
        interviews=interview_data,
        notes=notes,
        exports=exports,
        candidate_reports=reports,
        hiring_inputs=given,
        history=history,
        people=people,
    )
