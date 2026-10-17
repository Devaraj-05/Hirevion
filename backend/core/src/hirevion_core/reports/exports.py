"""Report PDFs: rendered once from the document a reader saw, stored, and handed out only through
an audited download (SP-17; PRD §97 "Report downloaded")."""

from __future__ import annotations

import hashlib
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.errors import NotFound
from hirevion_core.db.session import Database
from hirevion_core.ids import uuid7
from hirevion_core.models import ReportExport
from hirevion_core.reports import blocks as b
from hirevion_core.reports.blocks import Document
from hirevion_core.reports.html import render_html
from hirevion_core.reports.pdf import PdfRenderer, footer_text
from hirevion_core.storage.paths import BlobPath, candidate_blob, interview_blob
from hirevion_core.storage.service import StorageService

PDF = "application/pdf"
LIST_LIMIT = 100


async def render_pdf(renderer: PdfRenderer, doc: Document) -> bytes:
    """The PDF of `doc`. Raises `PdfUnavailable` where there is no browser to render with."""
    moment = datetime.fromisoformat(doc["generated_at"])
    return await renderer.render(render_html(doc), footer=footer_text(doc["title"], moment))


def blob_for(
    organization_id: UUID,
    export_id: UUID,
    kind: str,
    interview_id: UUID | None,
    candidate_id: UUID | None,
) -> BlobPath:
    name = f"{kind.replace('_', '-')}-{export_id}.pdf"
    if interview_id is not None:
        return interview_blob(organization_id, interview_id, "report", name)
    if candidate_id is None:
        raise ValueError("an export belongs to an interview or a candidate")
    return candidate_blob(organization_id, candidate_id, f"report-{name}")


async def store_export(
    db: Database,
    storage: StorageService,
    organization_id: UUID,
    doc: Document,
    pdf: bytes,
    *,
    renderer: str,
    kind: str,
    interview_id: UUID | None = None,
    candidate_id: UUID | None = None,
    requested_by: UUID | None = None,
    candidate_account_id: UUID | None = None,
    audience: str = "internal",
) -> ReportExport:
    """Keeps the PDF in blob storage and its row in `report_exports`."""
    export_id = uuid7()
    path = blob_for(organization_id, export_id, kind, interview_id, candidate_id)
    await storage.put(path, pdf, PDF)
    row = ReportExport(
        id=export_id,
        organization_id=organization_id,
        kind=kind,
        audience=audience,
        interview_id=interview_id,
        candidate_id=candidate_id,
        requested_by=requested_by,
        candidate_account_id=candidate_account_id,
        blob_path=str(path),
        bytes=len(pdf),
        sha256=hashlib.sha256(pdf).hexdigest(),
        document_sha256=b.digest(doc),
        renderer=renderer,
    )
    async with db.tenant(organization_id) as session:
        session.add(row)
        await session.flush()
        await session.refresh(row)
        session.expunge(row)
    return row


async def list_exports(
    session: AsyncSession,
    *,
    interview_id: UUID | None = None,
    candidate_id: UUID | None = None,
    audience: str = "internal",
) -> list[ReportExport]:
    statement = select(ReportExport).where(ReportExport.audience == audience)
    if interview_id is not None:
        statement = statement.where(ReportExport.interview_id == interview_id)
    if candidate_id is not None:
        statement = statement.where(ReportExport.candidate_id == candidate_id)
    rows = await session.scalars(
        statement.order_by(ReportExport.created_at.desc(), ReportExport.id.desc()).limit(LIST_LIMIT)
    )
    return list(rows.all())


async def get_export(session: AsyncSession, export_id: UUID) -> ReportExport:
    row = await session.get(ReportExport, export_id)
    if row is None:
        raise NotFound("export-not-found", "No such export")
    return row


async def read_export(storage: StorageService, row: ReportExport) -> bytes:
    """The stored PDF, checked against its recorded hash before it is handed out."""
    data = await storage.get(_path(row))
    if hashlib.sha256(data).hexdigest() != row.sha256:
        raise NotFound("export-corrupt", "That file no longer matches its record")
    return data


def _path(row: ReportExport) -> BlobPath:
    prefix = f"{row.organization_id}/"
    return BlobPath(row.organization_id, row.blob_path.removeprefix(prefix))


def file_name(row: ReportExport, reference: str) -> str:
    """A safe download name: `interview-report-IV-0042.pdf`."""
    kind = row.kind.replace("_", "-")
    return f"{kind}-report-{reference}.pdf"
