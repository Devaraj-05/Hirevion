"""Taking documents in: a pasted or uploaded job description becomes a `documents` row and an
outbox event for the `documents` consumer, in the request's transaction (ADR-0015)."""

from __future__ import annotations

import hashlib
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.actor import Actor
from hirevion_core.access.audit import record
from hirevion_core.access.errors import Conflict, Invalid, NotFound
from hirevion_core.documents.archive import MAX_ARCHIVE_BYTES
from hirevion_core.documents.files import (
    MAX_BYTES,
    RESUME_KINDS,
    DocumentRejected,
    check,
    display_name,
)
from hirevion_core.ids import uuid7
from hirevion_core.models import Document, Job
from hirevion_core.outbox import publish_event
from hirevion_core.storage.paths import BlobPath

DOCUMENTS_TOPIC = "documents"
JD_TYPES = frozenset({"pdf", "docx", "txt"})
TEXT_MAX = 100_000
CONTENT_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
    "png": "image/png",
    "jpeg": "image/jpeg",
    "tiff": "image/tiff",
    "zip": "application/zip",
}
_REJECTIONS = {
    "empty": "The file is empty",
    "too-large": "Upload a file of at most 10 MB",
    "unsupported-type": "Upload a PDF, Word (.docx) or text file",
    "archive-bomb": "The file expands to an unreasonable size",
    "unreadable": "The file can't be read",
}
RESUME_TYPES = RESUME_KINDS
_RESUME_REJECTIONS = {
    "empty": "The file is empty",
    "too-large": "Upload files of at most 10 MB, or ZIP archives of at most 50 MB",
    "unsupported-type": "Upload a PDF, Word (.docx), text, JPG, PNG or TIFF file, or a ZIP of them",
    "archive-bomb": "The file expands to an unreasonable size",
    "unreadable": "The file can't be read",
}


class BlobStore(Protocol):
    """What the pipeline needs of blob storage (`StorageService` in the app)."""

    async def put(self, path: BlobPath, data: bytes, content_type: str) -> None: ...
    async def get(self, path: BlobPath) -> bytes: ...
    async def delete(self, path: BlobPath) -> None: ...


async def _job(session: AsyncSession, job_id: UUID) -> Job:
    job = await session.get(Job, job_id)
    if job is None:
        raise NotFound("job-not-found", "No such job")
    return job


async def queue(session: AsyncSession, document: Document, action: str = "process") -> None:
    """Asks the `documents` consumer to work on `document`, once this transaction commits."""
    await publish_event(
        session,
        document.organization_id,
        DOCUMENTS_TOPIC,
        {"action": action, "document_id": str(document.id)},
        key=str(document.id),
    )


async def submit_jd_text(session: AsyncSession, actor: Actor, job_id: UUID, text: str) -> Document:
    job = await _job(session, job_id)
    text = text.strip()
    if not text:
        raise Invalid("text-required", "Paste the job description", field="text")
    if len(text) > TEXT_MAX:
        raise Invalid("too-long", f"Use at most {TEXT_MAX:,} characters", field="text")
    data = text.encode("utf-8")
    document = Document(
        organization_id=actor.organization_id,
        kind="jd",
        job_id=job.id,
        content_type="text/plain",
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        text=text,
        status="uploaded",
        created_by=actor.user_id,
    )
    session.add(document)
    await session.flush()
    await queue(session, document)
    await record(
        session,
        actor,
        "job.jd_uploaded",
        "job",
        job.id,
        details={"document_id": str(document.id), "source": "text"},
    )
    return document


async def submit_jd_file(
    session: AsyncSession,
    actor: Actor,
    job_id: UUID,
    data: bytes,
    filename: str,
    blobs: BlobStore,
) -> Document:
    job = await _job(session, job_id)
    try:
        kind = check(data, set(JD_TYPES))
    except DocumentRejected as error:
        raise Invalid(
            error.code, _REJECTIONS.get(error.code, "Unsupported file"), field="file"
        ) from error
    document_id = uuid7()
    key = f"jobs/{job.id}/{document_id}.{kind}"
    document = Document(
        id=document_id,
        organization_id=actor.organization_id,
        kind="jd",
        job_id=job.id,
        # Shown only; the stored file is named by its id.
        filename=display_name(filename),
        content_type=CONTENT_TYPES[kind],
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        blob_path=key,
        status="uploaded",
        created_by=actor.user_id,
    )
    await blobs.put(BlobPath(actor.organization_id, key), data, CONTENT_TYPES[kind])
    session.add(document)
    await session.flush()
    await queue(session, document)
    await record(
        session,
        actor,
        "job.jd_uploaded",
        "job",
        job.id,
        details={"document_id": str(document.id), "source": "file", "type": kind},
    )
    return document


async def submit_resume_file(
    session: AsyncSession,
    actor: Actor,
    job_id: UUID,
    data: bytes,
    filename: str,
    blobs: BlobStore,
    *,
    publish: bool = True,
) -> Document:
    """A resume, or a ZIP of resumes (kind `archive`), for a job (PRD §13). `publish=False`
    leaves queueing to the caller (the evaluation runs the pipeline itself)."""
    job = await _job(session, job_id)
    try:
        kind = check(data, set(RESUME_TYPES | {"zip"}), max_bytes=MAX_ARCHIVE_BYTES)
        if kind != "zip" and len(data) > MAX_BYTES:
            raise DocumentRejected("too-large")
    except DocumentRejected as error:
        message = _RESUME_REJECTIONS.get(error.code, "Unsupported file")
        raise Invalid(error.code, message, field="file") from error
    document_id = uuid7()
    key = f"jobs/{job.id}/resumes/{document_id}.{kind}"
    document = Document(
        id=document_id,
        organization_id=actor.organization_id,
        kind="archive" if kind == "zip" else "resume",
        job_id=job.id,
        filename=display_name(filename),
        content_type=CONTENT_TYPES[kind],
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        blob_path=key,
        status="uploaded",
        created_by=actor.user_id,
    )
    await blobs.put(BlobPath(actor.organization_id, key), data, CONTENT_TYPES[kind])
    session.add(document)
    await session.flush()
    if publish:
        await queue(session, document)
    await record(
        session,
        actor,
        "resume.uploaded",
        "job",
        job.id,
        details={"document_id": str(document.id), "type": kind},
    )
    return document


async def retry_document(session: AsyncSession, actor: Actor, document_id: UUID) -> Document:
    """Sends a failed document through the pipeline again."""
    document = await session.get(Document, document_id)
    if document is None:
        raise NotFound("document-not-found", "No such document")
    if document.status != "failed":
        raise Conflict("not-retryable", "Only a document that failed can be retried")
    document.status, document.error_code = "uploaded", None
    await session.flush()
    await queue(session, document)
    await record(
        session,
        actor,
        "document.retried",
        "document",
        document.id,
        details={"job_id": str(document.job_id) if document.job_id else None},
    )
    return document
