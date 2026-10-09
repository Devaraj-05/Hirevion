"""`/api/v1/jobs`, `/api/v1/documents` and `/api/v1/skills` (PRD §11, §12, §90). Every read and
change goes through the reader's resource scope first, so a job outside it doesn't exist for
them (ADR-0014)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated
from uuid import UUID

from fastapi import Depends, File, Form, Query, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_api.access.deps import idempotency_scope, own_tenant
from hirevion_api.authz import Principal, requires
from hirevion_api.deps import get_storage
from hirevion_api.idempotency import Idempotency, idempotency
from hirevion_api.jobs.schemas import (
    Choice,
    DocumentResponse,
    JdApply,
    JdResponse,
    JobChoices,
    JobCreate,
    JobFields,
    JobResponse,
    JobStatus,
    JobStatusChange,
    JobSummary,
    JobVersionResponse,
    SkillResponse,
    SkillSuggestion,
)
from hirevion_api.pagination import Page, PageParams, page_params, paginate
from hirevion_api.routing import api_router
from hirevion_core.access.errors import Invalid, NotFound, Refused
from hirevion_core.access.scope import resource_scope
from hirevion_core.documents import intake
from hirevion_core.documents.files import MAX_BYTES
from hirevion_core.jobs import jobs
from hirevion_core.jobs.jobs import JobDetail, JobFilters
from hirevion_core.jobs.taxonomy import search_skills
from hirevion_core.models import Department, Document, InterviewTemplate, Job, Team, User

router = api_router(tags=["jobs"])

ViewsJobs = Annotated[Principal, requires("jobs.view")]
ManagesJobs = Annotated[Principal, requires("jobs.create")]
RetriesDocuments = Annotated[Principal, requires("jobs.create", "candidates.manage")]
Idempotent = Annotated[Idempotency, Depends(idempotency)]
# Enough for any organisation this release serves; SP-22 brings a people search.
PEOPLE_MAX = 2000
# The templates a job can default to; the create-interview dialog reads as many.
TEMPLATES_MAX = 100


def reference(number: int) -> str:
    return f"JOB-{number:04d}"


def _float(value: object) -> float | None:
    return None if value is None else float(value)  # type: ignore[arg-type]


def document_response(document: Document) -> DocumentResponse:
    return DocumentResponse(
        id=document.id,
        status=document.status,  # type: ignore[arg-type]
        filename=document.filename,
        content_type=document.content_type,
        size=document.size,
        error_code=document.error_code,
        attempts=document.attempts,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def job_response(detail: JobDetail) -> JobResponse:
    job = detail.job
    return JobResponse(
        id=job.id,
        number=job.number,
        reference=reference(job.number),
        title=job.title,
        status=job.status,  # type: ignore[arg-type]
        version=job.version,
        department_id=job.department_id,
        department_name=detail.department_name,
        team_id=job.team_id,
        team_name=detail.team_name,
        location=job.location,
        work_model=job.work_model,  # type: ignore[arg-type]
        employment_type=job.employment_type,  # type: ignore[arg-type]
        experience_min=_float(job.experience_min),
        experience_max=_float(job.experience_max),
        description=job.description,
        responsibilities=job.responsibilities,
        qualifications=job.qualifications,
        domain=job.domain,
        salary_min=_float(job.salary_min),
        salary_max=_float(job.salary_max),
        salary_currency=job.salary_currency,
        recruiter_id=job.recruiter_id,
        recruiter_name=detail.recruiter_name,
        hiring_manager_id=job.hiring_manager_id,
        hiring_manager_name=detail.hiring_manager_name,
        interview_template_id=job.interview_template_id,
        interview_template_name=detail.interview_template_name,
        skills=[
            SkillResponse(
                name=skill.name,
                skill_id=skill.skill_id,
                importance=skill.importance,  # type: ignore[arg-type]
                min_years=_float(skill.min_years),
            )
            for skill in detail.skills
        ],
        jd_document_id=job.jd_document_id,
        latest_document=(
            document_response(detail.latest_document) if detail.latest_document else None
        ),
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


async def _summaries(session: AsyncSession, rows: Sequence[Job]) -> list[JobSummary]:
    department_ids = {job.department_id for job in rows if job.department_id}
    user_ids = {job.recruiter_id for job in rows if job.recruiter_id}
    departments: dict[UUID, str] = {}
    if department_ids:
        found = await session.execute(
            select(Department.id, Department.name).where(Department.id.in_(department_ids))
        )
        departments = {row.id: row.name for row in found}
    users: dict[UUID, str] = {}
    if user_ids:
        found = await session.execute(select(User.id, User.name).where(User.id.in_(user_ids)))
        users = {row.id: row.name for row in found}
    return [
        JobSummary(
            id=job.id,
            number=job.number,
            reference=reference(job.number),
            title=job.title,
            status=job.status,  # type: ignore[arg-type]
            department_id=job.department_id,
            department_name=departments.get(job.department_id) if job.department_id else None,
            location=job.location,
            work_model=job.work_model,  # type: ignore[arg-type]
            employment_type=job.employment_type,  # type: ignore[arg-type]
            recruiter_id=job.recruiter_id,
            recruiter_name=users.get(job.recruiter_id) if job.recruiter_id else None,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )
        for job in rows
    ]


async def _reachable(session: AsyncSession, principal: Principal, job_id: UUID) -> JobDetail:
    """The job, if the principal's scope reaches it; otherwise 404."""
    return await jobs.get_job(session, job_id, await resource_scope(session, principal.user_id))


async def _detail(session: AsyncSession, principal: Principal, job_id: UUID) -> JobResponse:
    await session.flush()
    session.expire_all()
    return job_response(await _reachable(session, principal, job_id))


# Jobs


@router.get("/jobs")
async def list_jobs(
    request: Request,
    principal: ViewsJobs,
    page: Annotated[PageParams, Depends(page_params)],
    status: JobStatus | None = None,
    department_id: UUID | None = None,
    recruiter_id: UUID | None = None,
    q: Annotated[
        str | None, Query(max_length=200, description="Part of the title, or JOB-0042.")
    ] = None,
) -> Page[JobSummary]:
    """The jobs the reader reaches, most recently changed first."""
    filters = JobFilters(
        status=status, department_id=department_id, recruiter_id=recruiter_id, query=q
    )
    async with own_tenant(request, principal) as session:
        scope = await resource_scope(session, principal.user_id)
        rows, next_cursor = await paginate(
            session,
            jobs.jobs_statement(scope, filters),
            [Job.updated_at, Job.id],
            page,
            descending=True,
        )
        return Page(items=await _summaries(session, rows), next_cursor=next_cursor)


@router.post("/jobs", status_code=201)
async def create_job(
    body: JobCreate, request: Request, principal: ManagesJobs, idem: Idempotent
) -> JobResponse:
    async with own_tenant(request, principal) as session:

        async def create() -> JobResponse:
            job = await jobs.create_job(session, principal.actor(request), body.changes())
            return await _detail(session, principal, job.id)

        return await idem.run(
            session, principal.organization_id, idempotency_scope(principal), create
        )


# Declared before /jobs/{job_id}, which would otherwise take "choices" for an id.
@router.get("/jobs/choices")
async def job_choices(request: Request, principal: ViewsJobs) -> JobChoices:
    """The departments, teams and people a job can be assigned to, and the active interview
    templates it can default to."""
    async with own_tenant(request, principal) as session:
        departments = await session.scalars(
            select(Department).where(Department.archived_at.is_(None)).order_by(Department.name)
        )
        teams = await session.scalars(
            select(Team).where(Team.archived_at.is_(None)).order_by(Team.name)
        )
        people = await session.scalars(
            select(User).where(User.status == "active").order_by(User.name).limit(PEOPLE_MAX)
        )
        interview_templates = await session.scalars(
            select(InterviewTemplate)
            .where(InterviewTemplate.status == "active")
            .order_by(InterviewTemplate.name)
            .limit(TEMPLATES_MAX)
        )
        return JobChoices(
            departments=[Choice.model_validate(row) for row in departments],
            teams=[Choice.model_validate(row) for row in teams],
            people=[Choice.model_validate(row) for row in people],
            interview_templates=[Choice.model_validate(row) for row in interview_templates],
        )


@router.get("/jobs/{job_id}")
async def get_job(job_id: UUID, request: Request, principal: ViewsJobs) -> JobResponse:
    async with own_tenant(request, principal) as session:
        return job_response(await _reachable(session, principal, job_id))


@router.patch("/jobs/{job_id}")
async def update_job(
    job_id: UUID, body: JobFields, request: Request, principal: ManagesJobs
) -> JobResponse:
    """Changes the fields sent; a change writes a new version."""
    async with own_tenant(request, principal) as session:
        await _reachable(session, principal, job_id)
        await jobs.update_job(session, principal.actor(request), job_id, body.changes())
        return await _detail(session, principal, job_id)


@router.post("/jobs/{job_id}/status")
async def change_job_status(
    job_id: UUID, body: JobStatusChange, request: Request, principal: ManagesJobs
) -> JobResponse:
    """Opens, pauses, closes or archives the job (PRD §11)."""
    async with own_tenant(request, principal) as session:
        await _reachable(session, principal, job_id)
        await jobs.set_status(session, principal.actor(request), job_id, body.status)
        return await _detail(session, principal, job_id)


@router.get("/jobs/{job_id}/versions")
async def list_job_versions(
    job_id: UUID, request: Request, principal: ViewsJobs
) -> list[JobVersionResponse]:
    async with own_tenant(request, principal) as session:
        await _reachable(session, principal, job_id)
        versions = await jobs.list_versions(session, job_id)
        return [JobVersionResponse.model_validate(version) for version in versions]


# Job descriptions


@router.post("/jobs/{job_id}/jd", status_code=202)
async def submit_job_description(
    job_id: UUID,
    request: Request,
    principal: ManagesJobs,
    idem: Idempotent,
    file: Annotated[UploadFile | None, File(description="A PDF, DOCX or TXT file.")] = None,
    text: Annotated[str | None, Form(description="The description, pasted.")] = None,
) -> DocumentResponse:
    """Takes a description as a file or as text; it's read in the background (PRD §12)."""
    async with own_tenant(request, principal) as session:
        await _reachable(session, principal, job_id)
        actor = principal.actor(request)

        async def create() -> DocumentResponse:
            if file is not None:
                data = await file.read(MAX_BYTES + 1)
                document = await intake.submit_jd_file(
                    session, actor, job_id, data, file.filename or "", get_storage(request)
                )
            elif text is not None and text.strip():
                document = await intake.submit_jd_text(session, actor, job_id, text)
            else:
                raise Invalid(
                    "description-required", "Upload a file or paste the description", field="file"
                )
            await session.flush()
            await session.refresh(document)
            return document_response(document)

        return await idem.run(
            session, principal.organization_id, idempotency_scope(principal), create
        )


@router.get("/jobs/{job_id}/jd")
async def get_job_description(job_id: UUID, request: Request, principal: ViewsJobs) -> JdResponse:
    """The job's latest description: its progress, and once read, what was found in it."""
    async with own_tenant(request, principal) as session:
        detail = await _reachable(session, principal, job_id)
        document = detail.latest_document
        if document is None:
            raise NotFound("no-description", "This job has no description yet")
        return JdResponse(
            **document_response(document).model_dump(),
            text=document.text,
            flags=document.flags,
            extraction=document.extraction,
        )


@router.post("/jobs/{job_id}/jd/apply")
async def apply_job_description(
    job_id: UUID, body: JdApply, request: Request, principal: ManagesJobs
) -> JobResponse:
    """Writes the reviewed fields into the job, as a new version (PRD §12)."""
    async with own_tenant(request, principal) as session:
        await _reachable(session, principal, job_id)
        await jobs.apply_jd(
            session, principal.actor(request), job_id, body.document_id, body.changes()
        )
        return await _detail(session, principal, job_id)


@router.post("/documents/{document_id}/retry")
async def retry_document(
    document_id: UUID, request: Request, principal: RetriesDocuments
) -> DocumentResponse:
    """Sends a document that failed through the pipeline again: a job description needs
    `jobs.create`, a resume `candidates.manage`."""
    async with own_tenant(request, principal) as session:
        document = await session.get(Document, document_id)
        if document is None or document.job_id is None:
            raise NotFound("document-not-found", "No such document")
        needed = "jobs.create" if document.kind == "jd" else "candidates.manage"
        if needed not in principal.permissions:
            raise Refused("forbidden", "You don't have permission to do this")
        await _reachable(session, principal, document.job_id)
        retried = await intake.retry_document(session, principal.actor(request), document_id)
        await session.flush()
        await session.refresh(retried)
        return document_response(retried)


# Skills


@router.get("/skills")
async def suggest_skills(
    request: Request,
    principal: ViewsJobs,
    q: Annotated[str, Query(max_length=100, description="The start of a skill or alias.")],
    limit: Annotated[int, Query(ge=1, le=25)] = 10,
) -> list[SkillSuggestion]:
    """Skills from the shared taxonomy for a typed name (prefix matches first)."""
    async with own_tenant(request, principal) as session:
        skills = await search_skills(session, q, limit)
        return [SkillSuggestion.model_validate(skill) for skill in skills]
