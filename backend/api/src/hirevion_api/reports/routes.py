"""Reports (SP-17; PRD §68, §69, §97, §99): the interview, proctoring, coding and internal
candidate reports as documents; their PDFs; and the candidate-visible report a recruiter approves.

Looking at a report, exporting it, downloading it and releasing it are each audited
(`report.viewed`, `.exported`, `.downloaded`, `.released`). A report is only built for a reader
whose scope reaches the interview or candidate, and only from what their permissions cover."""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_api.access.deps import own_tenant, scoped_interview
from hirevion_api.authz import Principal, requires
from hirevion_api.deps import get_db, get_redis, get_storage
from hirevion_api.problems import ProblemError
from hirevion_api.reports import schemas
from hirevion_api.reports.schemas import (
    CandidateReportBody,
    CandidateReportItem,
    CandidateReportResponse,
    CandidateReportSettings,
    ExportBody,
    ReleasedItem,
    ReportDocument,
    ReportExportList,
    ReportExportResponse,
    WithdrawBody,
)
from hirevion_api.routing import api_router
from hirevion_core.access import audit
from hirevion_core.access.errors import Conflict, Invalid, NotFound
from hirevion_core.access.scope import resource_scope
from hirevion_core.hiring import workflow
from hirevion_core.interviews import assignment
from hirevion_core.interviews.lifecycle import reference
from hirevion_core.models import ReportExport, User
from hirevion_core.reports import candidate as candidate_report
from hirevion_core.reports import coding, exports, visible
from hirevion_core.reports import interview as interview_report
from hirevion_core.reports import proctoring as proctoring_report
from hirevion_core.reports.blocks import Document
from hirevion_core.reports.candidate360 import load_candidate_360
from hirevion_core.reports.data import InterviewData, load_interview_data, user_names
from hirevion_core.reports.pdf import PdfRenderer, PdfUnavailable
from hirevion_core.reports.timeline import allowed_sources

log = logging.getLogger(__name__)
router = api_router(tags=["reports"])

ViewsInterviewReport = Annotated[Principal, requires("reports.interview.view")]
ViewsProctoringReport = Annotated[Principal, requires("reports.proctoring.view")]
ViewsCandidateReport = Annotated[Principal, requires("reports.candidate.view")]
Exports = Annotated[Principal, requires("reports.export")]
Releases = Annotated[Principal, requires("reports.release")]
ReadsSettings = Annotated[Principal, requires("reports.view")]
ManagesOrganization = Annotated[Principal, requires("admin.organization.manage")]

AUDIT_QUIET = 300
# What a reader needs to hold, besides the route's own permission, to see each kind.
KIND_PERMISSION = {
    "interview": "reports.interview.view",
    "coding": "reports.interview.view",
    "proctoring": "reports.proctoring.view",
    "candidate": "reports.candidate.view",
    "candidate_visible": "reports.candidate.view",
}


def _may_see(principal: Principal, kind: str) -> bool:
    """Whether the reader may see a stored PDF of this kind. A stored interview report holds the
    integrity signals and the people's side of the file whatever its reader asked for, so
    it is for readers who may see both."""
    if KIND_PERMISSION[kind] not in principal.permissions:
        return False
    if kind == "interview":
        return {"proctoring", "recruiter"} <= allowed_sources(principal.permissions)
    return True


def _needs(principal: Principal, kind: str) -> None:
    if not _may_see(principal, kind):
        raise ProblemError(403, "forbidden", "You don't have permission to do this")


async def _viewed(
    request: Request,
    session: AsyncSession,
    principal: Principal,
    kind: str,
    resource_type: str,
    resource_id: UUID,
) -> None:
    """Audits a look at a report; a page that reloads is recorded once every five minutes."""
    key = f"hv:rp:audit:report.viewed:{principal.user_id}:{kind}:{resource_id}"
    if not await get_redis(request).set(key, "1", nx=True, ex=AUDIT_QUIET):
        return
    await audit.record(
        session,
        principal.actor(request),
        "report.viewed",
        resource_type,
        resource_id,
        details={"kind": kind},
    )


def _pdf_unavailable() -> ProblemError:
    return ProblemError(
        503,
        "pdf-unavailable",
        "PDF export isn't available",
        "The PDF renderer (Chromium) isn't installed on this server. The web view still works.",
    )


def _renderer(request: Request) -> PdfRenderer:
    renderer = getattr(request.app.state, "pdf_renderer", None)
    if renderer is None:
        raise _pdf_unavailable()
    return renderer  # type: ignore[no-any-return]


# The reports as documents.


@router.get("/interviews/{interview_id}/reports/interview")
async def get_interview_report(
    interview_id: UUID, request: Request, principal: ViewsInterviewReport
) -> ReportDocument:
    """The interview report: PRD §69's thirteen sections. Viewing it is audited."""
    async with own_tenant(request, principal) as session:
        interview = await scoped_interview(session, principal, interview_id)
        data = await load_interview_data(session, interview)
        doc = interview_report.interview_report(data, principal.permissions)
        await _viewed(request, session, principal, "interview", "interview", interview.id)
    return schemas.document_of(doc)


@router.get("/interviews/{interview_id}/reports/proctoring")
async def get_proctoring_report_document(
    interview_id: UUID, request: Request, principal: ViewsProctoringReport
) -> ReportDocument:
    """The proctoring report: PRD §68's fourteen sections, with no single score. Viewing it is
    audited."""
    async with own_tenant(request, principal) as session:
        interview = await scoped_interview(session, principal, interview_id)
        data = await load_interview_data(session, interview)
        doc = proctoring_report.proctoring_report(data)
        await _viewed(request, session, principal, "proctoring", "interview", interview.id)
    return schemas.document_of(doc)


@router.get("/interviews/{interview_id}/reports/coding")
async def get_coding_report(
    interview_id: UUID, request: Request, principal: ViewsInterviewReport
) -> ReportDocument:
    """The coding report: what the interview recorded of its coding so far (the coding service
    is SP-16). Viewing it is audited."""
    async with own_tenant(request, principal) as session:
        interview = await scoped_interview(session, principal, interview_id)
        data = await load_interview_data(session, interview)
        doc = coding.coding_report(data)
        await _viewed(request, session, principal, "coding", "interview", interview.id)
    return schemas.document_of(doc)


@router.get("/candidates/{candidate_id}/report")
async def get_candidate_report(
    candidate_id: UUID, request: Request, principal: ViewsCandidateReport
) -> ReportDocument:
    """The internal candidate report: the whole file on one candidate, for the people who
    decide. Confidential; never shown to the candidate. Viewing it is audited."""
    async with own_tenant(request, principal) as session:
        scope = await resource_scope(session, principal.user_id)
        c360 = await load_candidate_360(session, candidate_id, scope, principal.permissions)
        doc = await candidate_report.candidate_report(session, c360)
        await _viewed(request, session, principal, "candidate", "candidate", candidate_id)
    return schemas.document_of(doc)


# PDFs.


async def _document_for(
    session: AsyncSession,
    principal: Principal,
    body: ExportBody,
) -> tuple[Document, str]:
    """The document to export and the reference its file is named by."""
    scope = await resource_scope(session, principal.user_id)
    if body.kind == "candidate":
        if body.candidate_id is None:
            raise Invalid("candidate-required", "Say which candidate", field="candidate_id")
        c360 = await load_candidate_360(session, body.candidate_id, scope, principal.permissions)
        doc = await candidate_report.candidate_report(session, c360)
        return doc, f"C-{str(body.candidate_id)[:8]}"
    if body.interview_id is None:
        raise Invalid("interview-required", "Say which interview", field="interview_id")
    interview = await assignment.get_interview(
        session, body.interview_id, scope, reviewer_only=principal.reviewer_only
    )
    ref = reference(interview.number)
    if body.kind == "candidate_visible":
        report = await visible.get_report(session, interview.id)
        if report is None or report.status != "released":
            raise Conflict("not-released", "Only a released report can be exported")
        data = await load_interview_data(session, interview, with_transcript=False)
        return visible.visible_document(interview, data.job, report), ref
    data = await load_interview_data(session, interview)
    if body.kind == "interview":
        return interview_report.interview_report(data, principal.permissions), ref
    builders = {
        "proctoring": proctoring_report.proctoring_report,
        "coding": coding.coding_report,
    }
    return builders[body.kind](data), ref


def _export_response(row: ReportExport, people: dict[UUID, str]) -> ReportExportResponse:
    return ReportExportResponse(
        id=row.id,
        kind=row.kind,  # type: ignore[arg-type]
        interview_id=row.interview_id,
        candidate_id=row.candidate_id,
        bytes=row.bytes,
        sha256=row.sha256,
        renderer=row.renderer,
        requested_by=row.requested_by,
        requested_by_name=people.get(row.requested_by) if row.requested_by else None,
        created_at=row.created_at,
    )


async def _names(session: AsyncSession, rows: list[ReportExport]) -> dict[UUID, str]:
    return await user_names(session, [row.requested_by for row in rows])


@router.post("/report-exports", status_code=201)
async def create_report_export(
    body: ExportBody, request: Request, principal: Exports
) -> ReportExportResponse:
    """Renders a report to a PDF, keeps it and audits it. The reader needs the permission to see
    that kind of report as well as `reports.export`."""
    _needs(principal, body.kind)
    renderer = _renderer(request)
    storage = get_storage(request)
    async with own_tenant(request, principal) as session:
        doc, _ = await _document_for(session, principal, body)
    try:
        pdf = await exports.render_pdf(renderer, doc)
    except PdfUnavailable as error:
        raise _pdf_unavailable() from error
    row = await exports.store_export(
        get_db(request),
        storage,  # type: ignore[arg-type]
        principal.organization_id,
        doc,
        pdf,
        renderer=renderer.name,
        kind=body.kind,
        interview_id=body.interview_id if body.kind != "candidate" else None,
        candidate_id=body.candidate_id if body.kind == "candidate" else None,
        requested_by=principal.user_id,
        audience="internal",
    )
    async with own_tenant(request, principal) as session:
        await audit.record(
            session,
            principal.actor(request),
            "report.exported",
            "interview" if row.interview_id else "candidate",
            row.interview_id or row.candidate_id,
            details={"kind": row.kind, "export_id": str(row.id), "bytes": row.bytes},
        )
        people = await _names(session, [row])
    return _export_response(row, people)


@router.get("/report-exports")
async def list_report_exports(
    request: Request,
    principal: Exports,
    interview_id: UUID | None = None,
    candidate_id: UUID | None = None,
) -> ReportExportList:
    """The PDFs made of an interview's or a candidate's reports, newest first."""
    if (interview_id is None) == (candidate_id is None):
        raise Invalid("subject-required", "Name an interview or a candidate")
    async with own_tenant(request, principal) as session:
        scope = await resource_scope(session, principal.user_id)
        if interview_id is not None:
            await assignment.get_interview(
                session, interview_id, scope, reviewer_only=principal.reviewer_only
            )
        else:
            await load_candidate_360(session, candidate_id, scope, principal.permissions)  # type: ignore[arg-type]
        rows = await exports.list_exports(
            session, interview_id=interview_id, candidate_id=candidate_id
        )
        rows = [r for r in rows if _may_see(principal, r.kind)]
        people = await _names(session, rows)
    return ReportExportList(items=[_export_response(row, people) for row in rows])


@router.get("/report-exports/{export_id}/download")
async def download_report_export(export_id: UUID, request: Request, principal: Exports) -> Response:
    """The stored PDF. Each download is audited, and the file is checked against its recorded
    hash before it is sent."""
    storage = get_storage(request)
    async with own_tenant(request, principal) as session:
        row = await exports.get_export(session, export_id)
        if row.audience != "internal":
            raise NotFound("export-not-found", "No such export")
        _needs(principal, row.kind)
        scope = await resource_scope(session, principal.user_id)
        if row.interview_id is not None:
            interview = await assignment.get_interview(
                session, row.interview_id, scope, reviewer_only=principal.reviewer_only
            )
            name = exports.file_name(row, reference(interview.number))
        else:
            await load_candidate_360(
                session,
                row.candidate_id,  # type: ignore[arg-type]
                scope,
                principal.permissions,
            )
            name = exports.file_name(row, f"C-{str(row.candidate_id)[:8]}")
        await audit.record(
            session,
            principal.actor(request),
            "report.downloaded",
            "interview" if row.interview_id else "candidate",
            row.interview_id or row.candidate_id,
            details={"kind": row.kind, "export_id": str(row.id), "sha256": row.sha256},
        )
    data = await exports.read_export(storage, row)  # type: ignore[arg-type]
    return Response(
        data,
        media_type=exports.PDF,
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


# The candidate-visible report.


async def _state(
    session: AsyncSession, principal: Principal, data: InterviewData
) -> CandidateReportResponse:
    interview = data.interview
    allowed = await visible.allowed_items(session, principal.organization_id)
    report = await visible.get_report(session, interview.id)
    ready = interview.status in workflow.FINISHED
    drafts = visible.draft_items(data) if ready else {}
    saved = report.items if report is not None else {}
    items = []
    for key in visible.ITEMS:
        value = {**drafts.get(key, {"text": "", "include": False}), **saved.get(key, {})}
        items.append(
            CandidateReportItem(
                key=key,
                title=visible.ITEM_TITLES[key],
                text=str(value.get("text", "")),
                include=bool(value.get("include")),
                allowed=allowed[key],
            )
        )
    approver = None
    if report is not None and report.approved_by is not None:
        approver = await session.get(User, report.approved_by)
    return CandidateReportResponse(
        interview_id=interview.id,
        status=report.status if report is not None else "none",  # type: ignore[arg-type]
        ready=ready,
        items=items,
        released=[ReleasedItem(**item) for item in visible.released_list(report)]
        if report is not None and report.status == "released"
        else [],
        approved_by=report.approved_by if report is not None else None,
        approved_by_name=approver.name if approver is not None else None,
        approved_at=report.approved_at if report is not None else None,
        withdrawn_at=report.withdrawn_at if report is not None else None,
        withdrawn_reason=report.withdrawn_reason if report is not None else None,
    )


@router.get("/interviews/{interview_id}/candidate-report")
async def get_candidate_visible_report(
    interview_id: UUID, request: Request, principal: ViewsCandidateReport
) -> CandidateReportResponse:
    """What the candidate may be shown (PRD §99): the draft, which items the organisation allows
    and, once approved, exactly what was released."""
    async with own_tenant(request, principal) as session:
        interview = await scoped_interview(session, principal, interview_id)
        data = await load_interview_data(session, interview, with_transcript=False)
        return await _state(session, principal, data)


@router.put("/interviews/{interview_id}/candidate-report")
async def save_candidate_visible_report(
    interview_id: UUID, body: CandidateReportBody, request: Request, principal: Releases
) -> CandidateReportResponse:
    """Saves the recruiter's edits to the draft. A released report must be withdrawn first."""
    async with own_tenant(request, principal) as session:
        interview = await scoped_interview(session, principal, interview_id)
        data = await load_interview_data(session, interview, with_transcript=False)
        await visible.save_draft(
            session,
            principal.actor(request),
            data,
            {key: item.model_dump() for key, item in body.items.items()},
        )
        return await _state(session, principal, data)


@router.post("/interviews/{interview_id}/candidate-report/approve")
async def approve_candidate_visible_report(
    interview_id: UUID, request: Request, principal: Releases
) -> CandidateReportResponse:
    """Releases the report to the candidate's portal: what the organisation allows and the
    recruiter included, frozen as it reads now. Audited."""
    async with own_tenant(request, principal) as session:
        interview = await scoped_interview(session, principal, interview_id)
        data = await load_interview_data(session, interview, with_transcript=False)
        await visible.approve(session, principal.actor(request), data)
        return await _state(session, principal, data)


@router.post("/interviews/{interview_id}/candidate-report/withdraw")
async def withdraw_candidate_visible_report(
    interview_id: UUID, body: WithdrawBody, request: Request, principal: Releases
) -> CandidateReportResponse:
    """Takes a released report off the candidate's portal, with the reason. Audited."""
    async with own_tenant(request, principal) as session:
        interview = await scoped_interview(session, principal, interview_id)
        data = await load_interview_data(session, interview, with_transcript=False)
        await visible.withdraw(session, principal.actor(request), interview, body.reason)
        return await _state(session, principal, data)


@router.get("/organization/candidate-report")
async def get_candidate_report_settings(
    request: Request, principal: ReadsSettings
) -> CandidateReportSettings:
    """Which of PRD §99's five items the organisation lets recruiters release."""
    async with own_tenant(request, principal) as session:
        return CandidateReportSettings(
            items=await visible.allowed_items(session, principal.organization_id)
        )


@router.put("/organization/candidate-report")
async def put_candidate_report_settings(
    body: CandidateReportSettings, request: Request, principal: ManagesOrganization
) -> CandidateReportSettings:
    async with own_tenant(request, principal) as session:
        saved = await visible.save_allowed_items(session, principal.actor(request), body.items)
    return CandidateReportSettings(items=saved)
