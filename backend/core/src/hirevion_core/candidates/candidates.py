"""Reading candidates within the resource scope (ADR-0014): someone limited to their teams sees
the candidates who applied to jobs they reach, and those they uploaded themselves."""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import ColumnElement, Select, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.errors import NotFound
from hirevion_core.access.scope import ResourceScope, scope_clause
from hirevion_core.models import Application, Candidate, CandidateSkill, Document, Job


@dataclass(frozen=True, slots=True)
class CandidateFilters:
    query: str | None = None
    """Part of the name or email, or the phone's digits."""
    job_id: UUID | None = None
    stage_group: str | None = None
    """One of `STAGE_GROUPS`: candidates with an application in one of its stages."""


# The /candidates tabs (PRD §7). A final decision (PRD §72) is a hiring status, so the decision
# tab also holds applications that were selected or rejected after an interview.
DECIDED = ("selected", "rejected")
STAGE_GROUPS: dict[str, tuple[str, ...]] = {
    "screening": ("uploaded", "parsed", "screened", "ranked", "review", "on_hold"),
    "shortlisted": ("shortlisted",),
    "interview": ("interview",),
    "completed": ("interviewed",),
    "decision": ("rejected",),
}


@dataclass(frozen=True, slots=True)
class CandidateDetail:
    candidate: Candidate
    skills: list[CandidateSkill]
    applications: list[tuple[Application, Job]]
    documents: list[Document]


def _escaped(query: str) -> str:
    return query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _stage_clause(group: str) -> ColumnElement[bool]:
    """The applications in a tab: by screening stage, and for the last two by the hiring status
    too (a decided application leaves "completed" and joins "decision")."""
    stages = Application.stage.in_(STAGE_GROUPS[group])
    if group == "decision":
        return stages | Application.hiring_status.in_(DECIDED)
    if group == "completed":
        return stages & Application.hiring_status.not_in(DECIDED)
    return stages


def candidates_statement(scope: ResourceScope, filters: CandidateFilters) -> Select[Candidate]:
    """The candidates `scope` reaches that match `filters`; the caller orders and pages it."""
    statement = select(Candidate)
    if not scope.organization_wide:
        applied_to_a_reachable_job = exists(
            select(Application.id)
            .join(Job, Job.id == Application.job_id)
            .where(
                Application.candidate_id == Candidate.id,
                scope_clause(scope, team_column=Job.team_id, owner_column=Job.recruiter_id),
            )
        )
        statement = statement.where(
            or_(applied_to_a_reachable_job, Candidate.created_by == scope.user_id)
        )
    if filters.job_id is not None or filters.stage_group is not None:
        applied = select(Application.id).where(Application.candidate_id == Candidate.id)
        if not scope.organization_wide:
            # A filter must not show that a candidate applied to a job the reader cannot see.
            applied = applied.join(Job, Job.id == Application.job_id).where(
                scope_clause(scope, team_column=Job.team_id, owner_column=Job.recruiter_id)
            )
        if filters.job_id is not None:
            applied = applied.where(Application.job_id == filters.job_id)
        if filters.stage_group is not None:
            applied = applied.where(_stage_clause(filters.stage_group))
        statement = statement.where(exists(applied))
    if filters.query and filters.query.strip():
        query = filters.query.strip()
        conditions: list[ColumnElement[bool]] = [
            Candidate.name.ilike(f"%{_escaped(query)}%", escape="\\"),
            Candidate.email.ilike(f"%{_escaped(query)}%", escape="\\"),
        ]
        digits = re.sub(r"\D", "", query)
        if len(digits) >= 4:
            conditions.append(Candidate.phone.contains(digits))
        statement = statement.where(or_(*conditions))
    return statement


async def get_candidate(
    session: AsyncSession, candidate_id: UUID, scope: ResourceScope
) -> CandidateDetail:
    """The candidate, if `scope` reaches them (otherwise they don't exist for this reader)."""
    candidate = await session.scalar(
        candidates_statement(scope, CandidateFilters()).where(Candidate.id == candidate_id)
    )
    if candidate is None:
        raise NotFound("candidate-not-found", "No such candidate")
    skills = await session.scalars(
        select(CandidateSkill)
        .where(CandidateSkill.candidate_id == candidate.id)
        .order_by(CandidateSkill.position)
    )
    applications_query = (
        select(Application, Job)
        .join(Job, Job.id == Application.job_id)
        .where(Application.candidate_id == candidate.id)
        .order_by(Application.created_at.desc())
    )
    if not scope.organization_wide:
        applications_query = applications_query.where(
            scope_clause(scope, team_column=Job.team_id, owner_column=Job.recruiter_id)
        )
    applications = [(row[0], row[1]) for row in await session.execute(applications_query)]
    documents_query = (
        select(Document)
        .where(Document.candidate_id == candidate.id)
        .order_by(Document.created_at.desc())
    )
    if not scope.organization_wide:
        reachable_jobs = select(Job.id).where(
            scope_clause(scope, team_column=Job.team_id, owner_column=Job.recruiter_id)
        )
        documents_query = documents_query.where(Document.job_id.in_(reachable_jobs))
    documents = await session.scalars(documents_query)
    return CandidateDetail(candidate, list(skills.all()), applications, list(documents.all()))


def applications_statement(job_id: UUID) -> Select[Application]:
    """A job's applications; the caller has already checked the job is in scope."""
    return select(Application).where(Application.job_id == job_id)
