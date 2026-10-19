"""Jobs (PRD §11): create, edit, open and close, with a version snapshot for every change and the
audit entries PRD §97 asks for ("Job created/changed"). Lists and reads honour the resource scope
(ADR-0014): a job belongs to its team and its recruiter."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, fields, replace
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Select, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access import UNSET, Unset
from hirevion_core.access.actor import Actor
from hirevion_core.access.audit import record
from hirevion_core.access.errors import Conflict, Invalid, NotFound
from hirevion_core.access.scope import ResourceScope, job_scope_clause
from hirevion_core.documents.intake import DOCUMENTS_TOPIC
from hirevion_core.jobs.taxonomy import resolve_skills
from hirevion_core.models import (
    Department,
    Document,
    InterviewTemplate,
    Job,
    JobSkill,
    JobVersion,
    Team,
    User,
)
from hirevion_core.models.job import EMPLOYMENT_TYPES, SKILL_IMPORTANCE, WORK_MODELS
from hirevion_core.outbox import publish_event

TITLE_MAX = 200
DESCRIPTION_MAX = 50_000
ITEM_MAX = 500
ITEMS_MAX = 50
SKILLS_MAX = 100
# The largest amount a salary column holds (NUMERIC(14, 2)).
SALARY_MAX = Decimal("999999999999.99")
# Fields the job's embedding is computed from (see `documents.pipeline.job_profile_text`).
EMBEDDED_FIELDS = frozenset(
    {"title", "description", "responsibilities", "qualifications", "domain", "skills"}
)
_CURRENCY = re.compile(r"[A-Z]{3}")

# Where a job may go from each status (PRD §11: Draft → Open → Paused → Closed → Archived).
TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"open"}),
    "open": frozenset({"paused", "closed"}),
    "paused": frozenset({"open", "closed"}),
    "closed": frozenset({"archived"}),
    "archived": frozenset(),
}


@dataclass(frozen=True, slots=True)
class SkillInput:
    name: str
    importance: str = "required"
    min_years: Decimal | None = None


@dataclass(frozen=True, slots=True)
class JobChanges:
    """What to set; `UNSET` leaves a field as it is, `None` clears an optional one."""

    title: str | Unset = UNSET
    department_id: UUID | Unset | None = UNSET
    team_id: UUID | Unset | None = UNSET
    location: str | Unset | None = UNSET
    work_model: str | Unset | None = UNSET
    employment_type: str | Unset = UNSET
    experience_min: Decimal | Unset | None = UNSET
    experience_max: Decimal | Unset | None = UNSET
    description: str | Unset = UNSET
    responsibilities: Sequence[str] | Unset = UNSET
    qualifications: Sequence[str] | Unset = UNSET
    domain: Sequence[str] | Unset = UNSET
    salary_min: Decimal | Unset | None = UNSET
    salary_max: Decimal | Unset | None = UNSET
    salary_currency: str | Unset | None = UNSET
    recruiter_id: UUID | Unset | None = UNSET
    hiring_manager_id: UUID | Unset | None = UNSET
    interview_template_id: UUID | Unset | None = UNSET
    """PRD §11's "Interview Template": what new interviews for the job use by default."""
    skills: Sequence[SkillInput] | Unset = UNSET


@dataclass(frozen=True, slots=True)
class JobFilters:
    status: str | None = None
    department_id: UUID | None = None
    recruiter_id: UUID | None = None
    query: str | None = None
    """Part of the title, or the job's number (`42` or `JOB-0042`)."""


@dataclass(frozen=True, slots=True)
class JobDetail:
    job: Job
    skills: list[JobSkill]
    department_name: str | None
    team_name: str | None
    recruiter_name: str | None
    hiring_manager_name: str | None
    latest_document: Document | None
    interview_template_name: str | None = None


# Validation


def _text(value: str, field: str, maximum: int, *, required: bool = False) -> str:
    cleaned = value.strip()
    if required and not cleaned:
        raise Invalid(f"{field.replace('_', '-')}-required", "This is required", field=field)
    if len(cleaned) > maximum:
        raise Invalid("too-long", f"Use at most {maximum} characters", field=field)
    return cleaned


def _items(values: Sequence[str], field: str) -> list[str]:
    items = [item for item in (value.strip() for value in values) if item]
    if len(items) > ITEMS_MAX:
        raise Invalid("too-many", f"Up to {ITEMS_MAX} items", field=field)
    if any(len(item) > ITEM_MAX for item in items):
        raise Invalid("too-long", f"Each item can have up to {ITEM_MAX} characters", field=field)
    return items


def _years(value: Decimal | None, field: str) -> Decimal | None:
    """Years as the database keeps them (one decimal, rounded as it rounds)."""
    if value is None:
        return None
    if not value.is_finite() or not Decimal(0) <= value <= Decimal(60):
        raise Invalid("invalid-years", "Use 0 to 60 years", field=field)
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _amount(value: Decimal | None, field: str) -> Decimal | None:
    if value is None:
        return None
    if not value.is_finite() or not Decimal(0) <= value <= SALARY_MAX:
        raise Invalid("invalid-salary", "Use an amount from 0 to 999,999,999,999.99", field=field)
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _check_skills(skills: Sequence[SkillInput]) -> None:
    if len(skills) > SKILLS_MAX:
        raise Invalid("too-many", f"Up to {SKILLS_MAX} skills", field="skills")
    if any(skill.importance not in SKILL_IMPORTANCE for skill in skills):
        raise Invalid("invalid-importance", "Unknown importance", field="skills")
    for skill in skills:
        _years(skill.min_years, "skills")


async def _member(
    session: AsyncSession, user_id: UUID | None, field: str, current: UUID | None = None
) -> UUID | None:
    """The person, who must be someone in the organisation who can still sign in. Only a new
    choice is checked: a job keeps a recruiter who was disabled since."""
    if user_id is None:
        return None
    if user_id == current:
        return user_id
    user = await session.get(User, user_id)
    if user is None or user.status == "disabled":
        raise Invalid("invalid-user", "Choose someone in this organisation", field=field)
    return user.id


async def _live[T: (Department, Team)](
    session: AsyncSession,
    model: type[T],
    row_id: UUID | None,
    field: str,
    current: UUID | None = None,
) -> UUID | None:
    """The department or team, which must not be archived (unless the job already has it)."""
    if row_id is None or row_id == current:
        return row_id
    row = await session.get(model, row_id)
    if row is None or row.archived_at is not None:
        raise Invalid("invalid-reference", "Choose a current one", field=field)
    return row.id


async def _apply(session: AsyncSession, job: Job, changes: JobChanges) -> list[str]:
    """Checks `changes`, writes them to `job` and returns the names of the fields that changed
    (`skills` included)."""
    if not isinstance(changes.skills, Unset):
        _check_skills(changes.skills)  # before anything is written to the job
    values: dict[str, Any] = {}
    if not isinstance(changes.title, Unset):
        values["title"] = _text(changes.title, "title", TITLE_MAX, required=True)
    if not isinstance(changes.description, Unset):
        values["description"] = _text(changes.description, "description", DESCRIPTION_MAX)
    if not isinstance(changes.location, Unset):
        values["location"] = _text(changes.location or "", "location", TITLE_MAX) or None
    if not isinstance(changes.work_model, Unset):
        if changes.work_model is not None and changes.work_model not in WORK_MODELS:
            raise Invalid("invalid-work-model", "Unknown work model", field="work_model")
        values["work_model"] = changes.work_model
    if not isinstance(changes.employment_type, Unset):
        if changes.employment_type not in EMPLOYMENT_TYPES:
            raise Invalid(
                "invalid-employment-type", "Unknown employment type", field="employment_type"
            )
        values["employment_type"] = changes.employment_type
    for name in ("responsibilities", "qualifications", "domain"):
        given = getattr(changes, name)
        if not isinstance(given, Unset):
            values[name] = _items(given, name)
    for name in ("experience_min", "experience_max"):
        given = getattr(changes, name)
        if not isinstance(given, Unset):
            values[name] = _years(given, name)
    for name in ("salary_min", "salary_max"):
        given = getattr(changes, name)
        if not isinstance(given, Unset):
            values[name] = _amount(given, name)
    if not isinstance(changes.salary_currency, Unset):
        currency = (changes.salary_currency or "").strip().upper() or None
        if currency is not None and not _CURRENCY.fullmatch(currency):
            raise Invalid(
                "invalid-currency", "Use a three-letter currency code", field="salary_currency"
            )
        values["salary_currency"] = currency
    if not isinstance(changes.department_id, Unset):
        values["department_id"] = await _live(
            session, Department, changes.department_id, "department_id", job.department_id
        )
    if not isinstance(changes.team_id, Unset):
        values["team_id"] = await _live(session, Team, changes.team_id, "team_id", job.team_id)
    for name in ("recruiter_id", "hiring_manager_id"):
        given = getattr(changes, name)
        if not isinstance(given, Unset):
            values[name] = await _member(session, given, name, getattr(job, name))
    if not isinstance(changes.interview_template_id, Unset):
        template_id = changes.interview_template_id
        # Only a new choice must be active: a job keeps a default that was archived since.
        if template_id is not None and template_id != job.interview_template_id:
            template = await session.get(InterviewTemplate, template_id)
            if template is None or template.status != "active":
                raise Invalid(
                    "invalid-template",
                    "Choose an active interview template",
                    field="interview_template_id",
                )
        values["interview_template_id"] = template_id

    def effective(name: str) -> Any:
        return values.get(name, getattr(job, name))

    low, high = effective("experience_min"), effective("experience_max")
    if low is not None and high is not None and low > high:
        raise Invalid("invalid-range", "The maximum is below the minimum", field="experience_max")
    low, high = effective("salary_min"), effective("salary_max")
    if low is not None and high is not None and low > high:
        raise Invalid("invalid-range", "The maximum is below the minimum", field="salary_max")

    changed = sorted(name for name, value in values.items() if getattr(job, name) != value)
    for name in changed:
        setattr(job, name, values[name])
    if not isinstance(changes.skills, Unset) and await _replace_skills(
        session, job, changes.skills
    ):
        changed = sorted([*changed, "skills"])
    return changed


async def _replace_skills(session: AsyncSession, job: Job, skills: Sequence[SkillInput]) -> bool:
    _check_skills(skills)
    rows: list[JobSkill] = []
    seen: set[str] = set()
    resolved = await resolve_skills(session, [skill.name for skill in skills])
    for given, skill in zip(skills, resolved, strict=True):
        # A skill named twice keeps the first mention's importance.
        if skill is None or skill.name.lower() in seen:
            continue
        seen.add(skill.name.lower())
        rows.append(
            JobSkill(
                organization_id=job.organization_id,
                job_id=job.id,
                position=len(rows),
                name=skill.name,
                skill_id=skill.skill_id,
                importance=given.importance,
                min_years=_years(given.min_years, "skills"),
            )
        )
    current = [(row.name, row.importance, row.min_years) for row in await _skills(session, job.id)]
    if current == [(row.name, row.importance, row.min_years) for row in rows]:
        return False
    await session.execute(delete(JobSkill).where(JobSkill.job_id == job.id))
    session.add_all(rows)
    await session.flush()
    return True


async def _skills(session: AsyncSession, job_id: UUID) -> list[JobSkill]:
    rows = await session.scalars(
        select(JobSkill).where(JobSkill.job_id == job_id).order_by(JobSkill.position)
    )
    return list(rows.all())


# Versions


def _json(value: Any) -> Any:
    if isinstance(value, Decimal | UUID):
        return str(value)
    if isinstance(value, list):
        return [_json(item) for item in value]
    return value


_SNAPSHOT_FIELDS = (
    *(f.name for f in fields(JobChanges) if f.name != "skills"),
    "status",
    "number",
    "jd_document_id",
)


async def _snapshot(session: AsyncSession, job: Job, reason: str, actor: Actor) -> None:
    skills = await _skills(session, job.id)
    snapshot = {name: _json(getattr(job, name)) for name in _SNAPSHOT_FIELDS}
    snapshot["skills"] = [
        {
            "name": skill.name,
            "skill_id": _json(skill.skill_id),
            "importance": skill.importance,
            "min_years": _json(skill.min_years),
        }
        for skill in skills
    ]
    session.add(
        JobVersion(
            organization_id=job.organization_id,
            job_id=job.id,
            version=job.version,
            snapshot=snapshot,
            reason=reason,
            created_by=actor.user_id,
        )
    )
    await session.flush()


def versions_statement(job_id: UUID) -> Select[JobVersion]:
    """A job's history; the caller orders and pages it."""
    return select(JobVersion).where(JobVersion.job_id == job_id)


async def list_versions(session: AsyncSession, job_id: UUID) -> list[JobVersion]:
    rows = await session.scalars(versions_statement(job_id).order_by(JobVersion.version))
    return list(rows.all())


async def bump(session: AsyncSession, actor: Actor, job: Job, reason: str) -> None:
    """Records a change to `job`: the next version and its snapshot."""
    job.version += 1
    await session.flush()
    await _snapshot(session, job, reason, actor)


# Jobs


async def create_job(session: AsyncSession, actor: Actor, changes: JobChanges) -> Job:
    if isinstance(changes.title, Unset):
        raise Invalid("title-required", "This is required", field="title")
    for _ in range(5):
        number = int(await session.scalar(select(func.coalesce(func.max(Job.number), 0))) or 0) + 1
        job = Job(
            organization_id=actor.organization_id,
            number=number,
            title="",
            responsibilities=[],
            qualifications=[],
            domain=[],
            status="draft",
            version=1,
            created_by=actor.user_id,
            # The creator is the recruiter unless someone else is named.
            recruiter_id=actor.user_id,
        )
        try:
            async with session.begin_nested():
                session.add(job)
                await session.flush()
        except IntegrityError as error:
            if "uq_jobs_organization_id_number" in str(error.orig):
                continue
            raise
        break
    else:
        raise Conflict("busy", "Too many jobs created at once; try again")
    changed = await _apply(session, job, changes)
    await session.flush()
    await _snapshot(session, job, "created", actor)
    await record(
        session,
        actor,
        "job.created",
        "job",
        job.id,
        details={"number": job.number, "title": job.title},
    )
    await _ask_for_embedding(session, job, changed)
    return job


async def _job(session: AsyncSession, job_id: UUID) -> Job:
    """The job, locked until the transaction ends: two edits at once take turns, and each
    starts from the version the other left."""
    job = await session.get(Job, job_id, with_for_update=True)
    if job is None:
        raise NotFound("job-not-found", "No such job")
    return job


async def _require_complete(session: AsyncSession, job: Job) -> None:
    """A job that is open (or about to be) has what screening needs: a title, a description and
    a required skill."""
    missing = [name for name in ("title", "description") if not getattr(job, name).strip()]
    if not any(skill.importance == "required" for skill in await _skills(session, job.id)):
        missing.append("required skills")
    if missing:
        raise Invalid(
            "job-incomplete", "Add what an open job needs first", detail=", ".join(missing)
        )


async def _ask_for_embedding(session: AsyncSession, job: Job, changed: Sequence[str]) -> None:
    """Queues the job's embedding again when something it is computed from changed."""
    if EMBEDDED_FIELDS.intersection(changed):
        await publish_event(
            session,
            job.organization_id,
            DOCUMENTS_TOPIC,
            {"action": "embed-job", "job_id": str(job.id)},
            key=str(job.id),
        )


async def update_job(session: AsyncSession, actor: Actor, job_id: UUID, changes: JobChanges) -> Job:
    job = await _job(session, job_id)
    changed = await _apply(session, job, changes)
    if changed:
        if job.status == "open":
            await _require_complete(session, job)
        await bump(session, actor, job, "edited")
        await record(session, actor, "job.updated", "job", job.id, details={"fields": changed})
        await _ask_for_embedding(session, job, changed)
    return job


async def set_status(session: AsyncSession, actor: Actor, job_id: UUID, status: str) -> Job:
    job = await _job(session, job_id)
    if status not in TRANSITIONS.get(job.status, frozenset()):
        raise Conflict(
            "invalid-transition",
            "A job can't go there from its current status",
            detail=f"{job.status} → {status}",
        )
    if status == "open":
        await _require_complete(session, job)
    previous, job.status = job.status, status
    await bump(session, actor, job, "status")
    await record(
        session,
        actor,
        "job.status_changed",
        "job",
        job.id,
        details={"from": previous, "to": status},
    )
    return job


async def apply_jd(
    session: AsyncSession, actor: Actor, job_id: UUID, document_id: UUID, changes: JobChanges
) -> Job:
    """Writes the recruiter's reviewed version of a parsed description into the job (PRD §12),
    then asks the documents consumer to re-embed the job."""
    job = await _job(session, job_id)
    document = await session.get(Document, document_id)
    if document is None or document.job_id != job.id or document.kind != "jd":
        raise NotFound("document-not-found", "No such document")
    if document.status != "parsed":
        raise Conflict("not-parsed", "The description hasn't been read yet")
    if isinstance(changes.description, Unset) and not job.description.strip() and document.text:
        changes = replace(changes, description=document.text[:DESCRIPTION_MAX])
    already_applied = job.jd_document_id == document.id
    changed = await _apply(session, job, changes)
    if already_applied and not changed:
        return job  # the same description with nothing new: no version, no second embedding
    job.jd_document_id = document.id
    if job.status == "open":
        await _require_complete(session, job)
    await bump(session, actor, job, "jd-applied")
    await record(
        session,
        actor,
        "job.jd_applied",
        "job",
        job.id,
        details={"document_id": str(document.id), "fields": changed},
    )
    await publish_event(
        session,
        job.organization_id,
        DOCUMENTS_TOPIC,
        {"action": "embed-job", "job_id": str(job.id)},
        key=str(job.id),
    )
    return job


def jobs_statement(scope: ResourceScope, filters: JobFilters) -> Select[Job]:
    """The jobs `scope` reaches that match `filters`; the caller orders and pages it."""
    statement = select(Job).where(job_scope_clause(scope))
    if filters.status is not None:
        statement = statement.where(Job.status == filters.status)
    if filters.department_id is not None:
        statement = statement.where(Job.department_id == filters.department_id)
    if filters.recruiter_id is not None:
        statement = statement.where(Job.recruiter_id == filters.recruiter_id)
    if filters.query and filters.query.strip():
        query = filters.query.strip()
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conditions: list[ColumnElement[bool]] = [Job.title.ilike(f"%{escaped}%", escape="\\")]
        number = re.fullmatch(r"(?:JOB-)?0*(\d{1,9})", query, re.IGNORECASE)
        if number:
            conditions.append(Job.number == int(number.group(1)))
        statement = statement.where(or_(*conditions))
    return statement


async def get_job(session: AsyncSession, job_id: UUID, scope: ResourceScope) -> JobDetail:
    """The job, if `scope` reaches it (otherwise it doesn't exist for this reader)."""
    job = await session.scalar(jobs_statement(scope, JobFilters()).where(Job.id == job_id))
    if job is None:
        raise NotFound("job-not-found", "No such job")

    async def name_of(
        model: type[Department | Team | User | InterviewTemplate], row_id: UUID | None
    ) -> str | None:
        if row_id is None:
            return None
        name = await session.scalar(select(model.name).where(model.id == row_id))
        return str(name) if name is not None else None

    latest = await session.scalar(
        select(Document)
        .where(Document.job_id == job.id, Document.kind == "jd")
        .order_by(Document.created_at.desc())
        .limit(1)
    )
    return JobDetail(
        job=job,
        skills=await _skills(session, job.id),
        department_name=await name_of(Department, job.department_id),
        team_name=await name_of(Team, job.team_id),
        recruiter_name=await name_of(User, job.recruiter_id),
        hiring_manager_name=await name_of(User, job.hiring_manager_id),
        latest_document=latest,
        interview_template_name=await name_of(InterviewTemplate, job.interview_template_id),
    )
