"""`/api/v1/jobs/{id}/resumes`, `/api/v1/jobs/{id}/applications`, `/api/v1/candidates` and
`/api/v1/documents/{id}/download` (PRD §13, §19, §90). Reads go through the resource scope: a
job or candidate outside it doesn't exist for the reader (ADR-0014)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Literal, Protocol, cast
from uuid import UUID

from fastapi import Depends, File, Query, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_api.access.deps import idempotency_scope, own_tenant
from hirevion_api.authz import Principal, requires
from hirevion_api.candidates.schemas import (
    ApplicationResponse,
    CandidateApplication,
    CandidateDocument,
    CandidateRef,
    CandidateResponse,
    CandidateSkillResponse,
    CandidateSummary,
    ResumeDocumentResponse,
)
from hirevion_api.deps import get_storage
from hirevion_api.idempotency import Idempotency, idempotency
from hirevion_api.jobs.routes import reference
from hirevion_api.jobs.schemas import DocumentStatus
from hirevion_api.pagination import Page, PageParams, page_params, paginate
from hirevion_api.routing import api_router
from hirevion_core.access.audit import record
from hirevion_core.access.errors import Conflict, NotFound, Refused
from hirevion_core.access.scope import resource_scope
from hirevion_core.candidates import candidates
from hirevion_core.candidates.candidates import CandidateFilters
from hirevion_core.documents import intake
from hirevion_core.documents.archive import MAX_ARCHIVE_BYTES
from hirevion_core.jobs import jobs
from hirevion_core.models import Application, Candidate, CandidateSkill, Document
from hirevion_core.storage.paths import BlobPath, download_name

router = api_router(tags=["candidates"])

ViewsCandidates = Annotated[Principal, requires("candidates.view")]
ManagesCandidates = Annotated[Principal, requires("candidates.manage")]
# A resume needs candidates.view, a job description jobs.view; the route checks which.
ViewsDocuments = Annotated[Principal, requires("candidates.view", "jobs.view")]
Idempotent = Annotated[Idempotency, Depends(idempotency)]
SUMMARY_SKILLS = 5


class SignsUrls(Protocol):
    def download_url(
        self, organization_id: UUID, path: BlobPath, *, filename: str | None = None
    ) -> str: ...


async def _job_in_scope(session: AsyncSession, principal: Principal, job_id: UUID) -> None:
    await jobs.get_job(session, job_id, await resource_scope(session, principal.user_id))


async def _summaries(
    session: AsyncSession, rows: Sequence[Candidate]
) -> dict[UUID, CandidateSummary]:
    ids = [candidate.id for candidate in rows]
    skills: dict[UUID, list[str]] = {candidate_id: [] for candidate_id in ids}
    if ids:
        found = await session.execute(
            select(CandidateSkill.candidate_id, CandidateSkill.name)
            .where(CandidateSkill.candidate_id.in_(ids), CandidateSkill.position < SUMMARY_SKILLS)
            .order_by(CandidateSkill.candidate_id, CandidateSkill.position)
        )
        for row in found:
            skills[row.candidate_id].append(row.name)
    return {
        candidate.id: CandidateSummary(
            id=candidate.id,
            name=candidate.name,
            email=candidate.email,
            location=candidate.location,
            headline=candidate.headline,
            skills=skills[candidate.id],
            flags=candidate.flags,
            created_at=candidate.created_at,
            updated_at=candidate.updated_at,
        )
        for candidate in rows
    }


def _resume_response(document: Document, candidate: Candidate | None) -> ResumeDocumentResponse:
    return ResumeDocumentResponse(
        id=document.id,
        kind=document.kind,  # type: ignore[arg-type]
        status=document.status,  # type: ignore[arg-type]
        filename=document.filename,
        content_type=document.content_type,
        size=document.size,
        error_code=document.error_code,
        attempts=document.attempts,
        parent_id=document.parent_id,
        flags=document.flags,
        candidate=CandidateRef(id=candidate.id, name=candidate.name) if candidate else None,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


# Resumes


@router.post("/jobs/{job_id}/resumes", status_code=202)
async def upload_resume(
    job_id: UUID,
    request: Request,
    principal: ManagesCandidates,
    idem: Idempotent,
    file: Annotated[
        UploadFile, File(description="A PDF, DOCX, TXT, JPG, PNG or TIFF resume, or a ZIP.")
    ],
) -> ResumeDocumentResponse:
    """Takes one resume, or a ZIP of them; each is read in the background (PRD §13)."""
    async with own_tenant(request, principal) as session:
        await _job_in_scope(session, principal, job_id)

        async def create() -> ResumeDocumentResponse:
            data = await file.read(MAX_ARCHIVE_BYTES + 1)
            document = await intake.submit_resume_file(
                session,
                principal.actor(request),
                job_id,
                data,
                file.filename or "",
                get_storage(request),
            )
            await session.flush()
            await session.refresh(document)
            return _resume_response(document, None)

        return await idem.run(
            session, principal.organization_id, idempotency_scope(principal), create
        )


@router.get("/jobs/{job_id}/resumes")
async def list_resumes(
    job_id: UUID,
    request: Request,
    principal: ViewsCandidates,
    page: Annotated[PageParams, Depends(page_params)],
    status: DocumentStatus | None = None,
    parent_id: Annotated[UUID | None, Query(description="Only this archive's entries.")] = None,
) -> Page[ResumeDocumentResponse]:
    """The job's resumes and archives, newest first, with their progress."""
    async with own_tenant(request, principal) as session:
        await _job_in_scope(session, principal, job_id)
        statement = select(Document).where(
            Document.job_id == job_id, Document.kind.in_(("resume", "archive"))
        )
        if status is not None:
            statement = statement.where(Document.status == status)
        if parent_id is not None:
            statement = statement.where(Document.parent_id == parent_id)
        rows, next_cursor = await paginate(
            session, statement, [Document.created_at, Document.id], page, descending=True
        )
        candidate_ids = {row.candidate_id for row in rows if row.candidate_id}
        people = {
            candidate.id: candidate
            for candidate in (
                await session.scalars(select(Candidate).where(Candidate.id.in_(candidate_ids)))
            ).all()
        }
        return Page(
            items=[
                _resume_response(row, people.get(row.candidate_id) if row.candidate_id else None)
                for row in rows
            ],
            next_cursor=next_cursor,
        )


@router.get("/jobs/{job_id}/applications")
async def list_applications(
    job_id: UUID,
    request: Request,
    principal: ViewsCandidates,
    page: Annotated[PageParams, Depends(page_params)],
) -> Page[ApplicationResponse]:
    """The job's candidates, newest application first."""
    async with own_tenant(request, principal) as session:
        await _job_in_scope(session, principal, job_id)
        rows, next_cursor = await paginate(
            session,
            candidates.applications_statement(job_id),
            [Application.created_at, Application.id],
            page,
            descending=True,
        )
        people = (
            await session.scalars(
                select(Candidate).where(Candidate.id.in_({row.candidate_id for row in rows}))
            )
        ).all()
        summaries = await _summaries(session, people)
        return Page(
            items=[
                ApplicationResponse(
                    id=row.id,
                    stage=row.stage,  # type: ignore[arg-type]
                    document_id=row.document_id,
                    candidate=summaries[row.candidate_id],
                    created_at=row.created_at,
                )
                for row in rows
            ],
            next_cursor=next_cursor,
        )


# Candidates


@router.get("/candidates")
async def list_candidates(
    request: Request,
    principal: ViewsCandidates,
    page: Annotated[PageParams, Depends(page_params)],
    q: Annotated[
        str | None, Query(max_length=200, description="Part of the name or email, or the phone.")
    ] = None,
    job_id: UUID | None = None,
    stage_group: Annotated[
        Literal["screening", "shortlisted", "interview", "completed", "decision"] | None,
        Query(description="The /candidates tab: candidates with an application at that stage."),
    ] = None,
) -> Page[CandidateSummary]:
    """The candidates the reader reaches, most recently updated first."""
    async with own_tenant(request, principal) as session:
        scope = await resource_scope(session, principal.user_id)
        rows, next_cursor = await paginate(
            session,
            candidates.candidates_statement(
                scope, CandidateFilters(query=q, job_id=job_id, stage_group=stage_group)
            ),
            [Candidate.updated_at, Candidate.id],
            page,
            descending=True,
        )
        summaries = await _summaries(session, rows)
        return Page(items=[summaries[row.id] for row in rows], next_cursor=next_cursor)


@router.get("/candidates/{candidate_id}")
async def get_candidate(
    candidate_id: UUID, request: Request, principal: ViewsCandidates
) -> CandidateResponse:
    """A candidate's parsed profile with its evidence, their applications and resumes."""
    async with own_tenant(request, principal) as session:
        detail = await candidates.get_candidate(
            session, candidate_id, await resource_scope(session, principal.user_id)
        )
        candidate = detail.candidate
        summary = (await _summaries(session, [candidate]))[candidate.id]
        return CandidateResponse(
            **summary.model_dump(),
            phone=candidate.phone,
            profile=candidate.profile,
            skill_details=[
                CandidateSkillResponse(
                    name=skill.name,
                    skill_id=skill.skill_id,
                    years=None if skill.years is None else float(skill.years),
                )
                for skill in detail.skills
            ],
            applications=[
                CandidateApplication(
                    id=application.id,
                    job_id=job.id,
                    job_reference=reference(job.number),
                    job_title=job.title,
                    stage=application.stage,  # type: ignore[arg-type]
                    hiring_status=application.hiring_status,  # type: ignore[arg-type]
                    created_at=application.created_at,
                )
                for application, job in detail.applications
            ],
            documents=[
                CandidateDocument(
                    id=document.id,
                    filename=document.filename,
                    content_type=document.content_type,
                    size=document.size,
                    status=document.status,  # type: ignore[arg-type]
                    flags=document.flags,
                    created_at=document.created_at,
                )
                for document in detail.documents
            ],
        )


# Downloads

# Statuses a document reaches only after its file was scanned and found clean.
_AFTER_THE_SCAN = frozenset({"extracting", "ocr", "parsing", "parsed"})
# Why a document fails before the scan finished: the scanner was down for good.
_BEFORE_THE_SCAN = frozenset({"retries-exhausted"})


def scanned(document: Document) -> bool:
    """Whether the file was scanned and found clean. An archive is opened, never scanned whole
    (its entries are, one by one), so only the entries can be downloaded."""
    if document.kind == "archive":
        return False
    if document.status in _AFTER_THE_SCAN:
        return True
    return document.status == "failed" and document.error_code not in _BEFORE_THE_SCAN | {None}


@router.get("/documents/{document_id}/download", status_code=307)
async def download_document(
    document_id: UUID, request: Request, principal: ViewsDocuments
) -> RedirectResponse:
    """A 5-minute link to the original file (audited for resumes)."""
    async with own_tenant(request, principal) as session:
        document = await session.get(Document, document_id)
        if document is None or document.job_id is None:
            raise NotFound("document-not-found", "No such document")
        needed = "jobs.view" if document.kind == "jd" else "candidates.view"
        if needed not in principal.permissions:
            raise Refused("forbidden", "You don't have permission to do this")
        await _job_in_scope(session, principal, document.job_id)
        if document.status == "quarantined":
            raise Conflict("quarantined", "This file was flagged as unsafe and can't be opened")
        if document.blob_path is None:
            raise NotFound("no-file", "This description was pasted, so there's no file")
        if not scanned(document):
            raise Conflict("not-scanned", "This file hasn't been checked for viruses yet")
        if document.kind != "jd":
            await record(
                session,
                principal.actor(request),
                "candidate.resume_downloaded",
                "document",
                document.id,
                details={
                    "candidate_id": str(document.candidate_id) if document.candidate_id else None
                },
            )
        signer = cast(SignsUrls, get_storage(request))
        url = signer.download_url(
            principal.organization_id,
            BlobPath(principal.organization_id, document.blob_path),
            filename=download_name(
                document.filename, "description" if document.kind == "jd" else "resume"
            ),
        )
    return RedirectResponse(url, status_code=307)
