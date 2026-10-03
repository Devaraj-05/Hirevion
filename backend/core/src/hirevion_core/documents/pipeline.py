"""The document pipeline (PRD §12, §13 and §14; master plan §6.6), run by the `documents` consumer:

    uploaded → scanning → extracting → (ocr) → parsing → parsed      (or quarantined / failed)

- **Job descriptions:** text, sections, then the JD extraction and the job's embedding.
- **Resumes:** text (OCR for images and pages without a text layer), safety flags, PII masking,
  the resume parse, then the candidate and its application. Exact copies of a resume already
  parsed reuse it, with no AI call.
- **Archives (ZIP):** scanned whole, then each entry becomes a resume document of its own.

Each step saves its status in its own transaction, so the processing view shows progress. An
outage (scanner or AI) leaves the document where it stopped and re-raises, so the consumer tries
again later; a bad file ends `failed` with a reason, and an infected one `quarantined`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from hirevion_core.ai import AiServices
from hirevion_core.ai.types import (
    AiBudgetExceeded,
    AiContext,
    AiOutputInvalid,
    AiRequestError,
)
from hirevion_core.candidates import dedupe, profiles
from hirevion_core.db.session import Database
from hirevion_core.documents import archive, hidden, ocr, pii
from hirevion_core.documents.files import DocumentRejected, sniff
from hirevion_core.documents.intake import CONTENT_TYPES, BlobStore, queue
from hirevion_core.documents.jd import extract_jd
from hirevion_core.documents.resume import ResumeResult, parse_resume
from hirevion_core.documents.scan import Scanner
from hirevion_core.documents.sections import detect, normalise
from hirevion_core.documents.text import ExtractedText, extract, needs_ocr
from hirevion_core.ids import uuid7
from hirevion_core.jobs.taxonomy import resolve_skills
from hirevion_core.models import Candidate, Document, Job, JobSkill
from hirevion_core.storage.paths import BlobPath

# How much of a document's text is embedded (the start says the most).
EMBED_CHARACTERS = 8_000
IMAGE_KINDS = ("png", "jpeg", "tiff")


@dataclass(frozen=True, slots=True)
class DocumentServices:
    db: Database
    blobs: BlobStore
    scanner: Scanner
    ai: AiServices
    scan: bool = True


@dataclass(frozen=True, slots=True)
class _Claimed:
    """What the pipeline needs of a document, read when it starts on it."""

    id: UUID
    kind: str
    job_id: UUID | None
    blob_path: str | None
    sha256: str | None
    pasted: str | None
    created_by: UUID | None


async def _set(
    services: DocumentServices, organization_id: UUID, document_id: UUID, **values: Any
) -> None:
    async with services.db.tenant(organization_id) as session:
        document = await session.get_one(Document, document_id)
        for name, value in values.items():
            setattr(document, name, value)


async def _fail(
    services: DocumentServices, organization_id: UUID, document_id: UUID, code: str
) -> None:
    await _set(services, organization_id, document_id, status="failed", error_code=code)


async def _embed(
    services: DocumentServices, organization_id: UUID, purpose: str, text: str, ref: str
) -> list[float]:
    context = AiContext(organization_id=organization_id, purpose=purpose, input_refs={"ref": ref})
    result = await services.ai.embeddings.embed(context, [text[:EMBED_CHARACTERS]])
    return result.vectors[0]


async def _claim(
    services: DocumentServices, organization_id: UUID, document_id: UUID
) -> _Claimed | None:
    async with services.db.tenant(organization_id) as session:
        document = await session.get(Document, document_id)
        if document is None or document.status in ("parsed", "quarantined"):
            return None
        document.attempts += 1
        document.status = "scanning" if document.blob_path else "extracting"
        return _Claimed(
            document.id,
            document.kind,
            document.job_id,
            document.blob_path,
            document.sha256,
            document.text,
            document.created_by,
        )


async def _scanned(
    services: DocumentServices, organization_id: UUID, claimed: _Claimed, blob_path: str
) -> bytes | None:
    """The file, once it's known to be clean; None when it was quarantined instead."""
    path = BlobPath(organization_id, blob_path)
    data = await services.blobs.get(path)
    # An archive isn't scanned whole: each entry becomes a document, scanned before it's read,
    # so one infected file doesn't sink the rest of a batch.
    if services.scan and claimed.kind != "archive":
        verdict = await services.scanner.scan(data)  # ScanUnavailable: retried later
        if not verdict.clean:
            quarantine = f"quarantine/{blob_path.rsplit('/', 1)[-1]}"
            await services.blobs.put(
                BlobPath(organization_id, quarantine), data, "application/octet-stream"
            )
            await services.blobs.delete(path)
            await _set(
                services,
                organization_id,
                claimed.id,
                status="quarantined",
                blob_path=quarantine,
                flags={"signature": verdict.signature},
            )
            return None
    return data


async def process_document(
    services: DocumentServices, organization_id: UUID, document_id: UUID
) -> None:
    claimed = await _claim(services, organization_id, document_id)
    if claimed is None:
        return
    if (
        claimed.kind == "resume"
        and claimed.sha256
        and await _reuse_copy(services, organization_id, claimed, claimed.sha256)
    ):
        return

    if claimed.blob_path is None:
        extracted = ExtractedText(claimed.pasted or "", 1, (claimed.pasted or "",))
    else:
        data = await _scanned(services, organization_id, claimed, claimed.blob_path)
        if data is None:
            return
        if claimed.kind == "archive":
            await _expand(services, organization_id, claimed, data)
            return
        await _set(services, organization_id, claimed.id, status="extracting")
        try:
            extracted, ocr_confidence = await _read(services, organization_id, claimed, data)
        except DocumentRejected as error:
            await _fail(services, organization_id, claimed.id, error.code)
            return
        except (AiOutputInvalid, AiRequestError):
            await _fail(services, organization_id, claimed.id, "ocr-failed")
            return
        except AiBudgetExceeded:
            await _fail(services, organization_id, claimed.id, "budget-exceeded")
            return
        if claimed.kind == "resume" and ocr_confidence is not None:
            extracted = _with_confidence(extracted, ocr_confidence)

    if claimed.kind == "jd":
        await _process_jd(services, organization_id, claimed, extracted)
    else:
        await _process_resume(services, organization_id, claimed, extracted)


# Reading files


@dataclass(frozen=True, slots=True)
class _OcrExtracted(ExtractedText):
    ocr_confidence: float | None = None


def _with_confidence(extracted: ExtractedText, confidence: float) -> ExtractedText:
    return _OcrExtracted(
        extracted.text,
        extracted.pages,
        extracted.page_texts,
        extracted.hidden,
        extracted.metadata,
        confidence,
    )


async def _read(
    services: DocumentServices, organization_id: UUID, claimed: _Claimed, data: bytes
) -> tuple[ExtractedText, float | None]:
    """The file's text, with OCR for image resumes and resume pages without a text layer."""
    kind = sniff(data) or "unknown"
    if claimed.kind == "resume" and kind in IMAGE_KINDS:
        await _set(services, organization_id, claimed.id, status="ocr")
        read = await ocr.read(services.ai, organization_id, data, kind, document_id=claimed.id)
        pages = tuple(read.page_texts[number] for number in sorted(read.page_texts))
        return ExtractedText("\f".join(pages), len(pages), pages), read.confidence
    extracted = extract(data, kind)
    missing = needs_ocr(extracted.page_texts) if claimed.kind == "resume" and kind == "pdf" else []
    if not missing:
        return extracted, None
    await _set(services, organization_id, claimed.id, status="ocr")
    read = await ocr.read(
        services.ai, organization_id, data, "pdf", missing, document_id=claimed.id
    )
    pages = tuple(
        read.page_texts.get(number, text)
        for number, text in enumerate(extracted.page_texts, start=1)
    )
    filled = ExtractedText(
        "\f".join(pages), extracted.pages, pages, extracted.hidden, extracted.metadata
    )
    return filled, read.confidence


# Job descriptions


async def _process_jd(
    services: DocumentServices, organization_id: UUID, claimed: _Claimed, raw: ExtractedText
) -> None:
    text, zero_width = normalise(raw.text)
    if not text:
        await _fail(services, organization_id, claimed.id, "no-text")
        return
    sections = [section.name for section in detect(text)]
    await _set(
        services,
        organization_id,
        claimed.id,
        status="parsing",
        text=text,
        pages=raw.pages,
        flags={"hidden_characters": zero_width},
    )
    try:
        result = await extract_jd(services.ai.llm, organization_id, text, document_id=claimed.id)
        vector = await _embed(services, organization_id, "jd.embed", text, str(claimed.id))
    except (AiOutputInvalid, AiRequestError):
        await _fail(services, organization_id, claimed.id, "ai-failed")
        return
    except AiBudgetExceeded:
        await _fail(services, organization_id, claimed.id, "budget-exceeded")
        return

    extraction = result.extraction
    async with services.db.tenant(organization_id) as session:
        required = await resolve_skills(session, [s.name for s in extraction.required_skills])
        preferred = await resolve_skills(session, [s.name for s in extraction.preferred_skills])

        def skills(items: list[Any], resolved: list[Any]) -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            seen: set[str] = set()
            for item, skill in zip(items, resolved, strict=True):
                if skill is None or skill.name.lower() in seen:
                    continue
                seen.add(skill.name.lower())
                out.append(
                    {
                        "name": skill.name,
                        "skill_id": str(skill.skill_id) if skill.skill_id else None,
                        "quote": item.quote,
                    }
                )
            return out

        document = await session.get_one(Document, claimed.id)
        document.status = "parsed"
        document.error_code = None
        document.extraction = {
            **extraction.model_dump(mode="json"),
            "required_skills": skills(extraction.required_skills, required),
            "preferred_skills": skills(extraction.preferred_skills, preferred),
            "dropped": result.dropped,
            "sections": sections,
            "model": result.model,
        }
        job = await session.get(Job, document.job_id) if document.job_id else None
        if job is not None and job.embedding is None:
            job.embedding = vector


# Resumes


def profile_text(profile: dict[str, Any]) -> str:
    """What a candidate's embedding is computed from: their work, never their name or contact."""
    lines: list[str] = []
    summary = profile.get("summary")
    if isinstance(summary, dict):
        lines.append(str(summary.get("value") or ""))
    lines.append("Skills: " + ", ".join(str(s.get("name")) for s in profile.get("skills") or []))
    for position in profile.get("positions") or []:
        lines.append(" ".join(str(position.get(key) or "") for key in ("title", "company")))
    for item in profile.get("projects") or []:
        lines.append(" ".join(str(item.get(key) or "") for key in ("name", "description")))
    for item in profile.get("education") or []:
        lines.append(" ".join(str(item.get(key) or "") for key in ("degree", "field")))
    return "\n".join(line.strip() for line in lines if line.strip())


async def _process_resume(
    services: DocumentServices, organization_id: UUID, claimed: _Claimed, raw: ExtractedText
) -> None:
    text, zero_width = normalise(raw.text)
    if not text:
        await _fail(services, organization_id, claimed.id, "no-text")
        return
    flags = hidden.inspect(raw, zero_width=zero_width)
    confidence = raw.ocr_confidence if isinstance(raw, _OcrExtracted) else None
    if confidence is not None and confidence < ocr.LOW_CONFIDENCE:
        flags["low_ocr_confidence"] = round(confidence, 2)
    masked = pii.mask(text)
    page_texts = [pii.mask(normalise(page)[0]).text for page in raw.page_texts] or [masked.text]
    await _set(
        services,
        organization_id,
        claimed.id,
        status="parsing",
        text=masked.text,
        pages=raw.pages,
        flags={**flags, "pii": masked.counts},
    )
    try:
        result = await parse_resume(
            services.ai.llm, organization_id, masked.text, page_texts, document_id=claimed.id
        )
        vector = await _embed(
            services,
            organization_id,
            "resume.embed",
            profile_text(result.profile) or masked.text,
            str(claimed.id),
        )
    except (AiOutputInvalid, AiRequestError):
        await _fail(services, organization_id, claimed.id, "ai-failed")
        return
    except AiBudgetExceeded:
        await _fail(services, organization_id, claimed.id, "budget-exceeded")
        return
    await _save_resume(services, organization_id, claimed.id, result, flags, vector, masked.text)


async def _save_resume(
    services: DocumentServices,
    organization_id: UUID,
    document_id: UUID,
    result: ResumeResult,
    flags: dict[str, Any],
    vector: list[float],
    text: str,
) -> None:
    async with services.db.tenant(organization_id) as session:
        document = await session.get_one(Document, document_id)
        await profiles.build(session, document, result, flags=flags, embedding=vector)
        document.status = "parsed"
        document.error_code = None
        document.extraction = {
            **result.profile,
            "dropped": result.dropped,
            "sections": [section.name for section in detect(text)],
            "model": result.model,
        }


async def _reuse_copy(
    services: DocumentServices, organization_id: UUID, claimed: _Claimed, sha256: str
) -> bool:
    """An exact copy of a resume already parsed takes its result; True when there was one."""
    async with services.db.tenant(organization_id) as session:
        copy = await dedupe.parsed_copy(session, sha256)
        if copy is None or copy.id == claimed.id or copy.candidate_id is None:
            return False
        document = await session.get_one(Document, claimed.id)
        candidate = await session.get_one(Candidate, copy.candidate_id)
        document.text, document.pages, document.extraction = copy.text, copy.pages, copy.extraction
        document.flags = {**copy.flags, "duplicate_of": str(copy.id)}
        await profiles.ensure_application(session, document, candidate)
        document.status, document.error_code = "parsed", None
    return True


# Archives


async def _expand(
    services: DocumentServices, organization_id: UUID, claimed: _Claimed, data: bytes
) -> None:
    """Each resume in the ZIP becomes a document of its own, queued in turn."""
    try:
        contents = archive.entries(data)
    except DocumentRejected as error:
        await _fail(services, organization_id, claimed.id, error.code)
        return
    async with services.db.tenant(organization_id) as session:
        done = await session.scalar(
            select(func.count()).select_from(Document).where(Document.parent_id == claimed.id)
        )
    if not done:  # a retry after a crash doesn't expand twice
        children = []
        for entry in contents.entries:
            child_id = uuid7()
            key = f"jobs/{claimed.job_id}/resumes/{child_id}.{entry.kind}"
            await services.blobs.put(
                BlobPath(organization_id, key), entry.data, CONTENT_TYPES[entry.kind]
            )
            children.append((child_id, key, entry))
        async with services.db.tenant(organization_id) as session:
            for child_id, key, entry in children:
                child = Document(
                    id=child_id,
                    organization_id=organization_id,
                    kind="resume",
                    job_id=claimed.job_id,
                    parent_id=claimed.id,
                    filename=entry.name[:255],
                    content_type=CONTENT_TYPES[entry.kind],
                    size=len(entry.data),
                    sha256=hashlib.sha256(entry.data).hexdigest(),
                    blob_path=key,
                    status="uploaded",
                    created_by=claimed.created_by,
                )
                session.add(child)
                await session.flush()
                await queue(session, child)
    await _set(
        services,
        organization_id,
        claimed.id,
        status="parsed",
        error_code=None,
        flags={"entries": len(contents.entries), "skipped": contents.skipped},
    )


# Jobs' embeddings


def job_profile_text(job: Job, skills: list[JobSkill]) -> str:
    """What a job's embedding is computed from once its profile is applied."""
    lines = [
        job.title,
        "Skills: " + ", ".join(skill.name for skill in skills),
        *job.responsibilities,
        *job.qualifications,
        *job.domain,
        job.description,
    ]
    return "\n".join(line for line in lines if line)


async def embed_job(services: DocumentServices, organization_id: UUID, job_id: UUID) -> None:
    async with services.db.tenant(organization_id) as session:
        job = await session.get(Job, job_id)
        if job is None:
            return
        skills = list(
            (
                await session.scalars(
                    select(JobSkill).where(JobSkill.job_id == job_id).order_by(JobSkill.position)
                )
            ).all()
        )
        text = job_profile_text(job, skills)
    vector = await _embed(services, organization_id, "job.embed", text, str(job_id))
    async with services.db.tenant(organization_id) as session:
        job = await session.get(Job, job_id)
        if job is not None:
            job.embedding = vector


async def handle_event(
    services: DocumentServices, organization_id: UUID, payload: dict[str, Any]
) -> None:
    """One `documents` stream event: process a document, or re-embed a job."""
    action = payload.get("action", "process")
    if action == "process":
        await process_document(services, organization_id, UUID(payload["document_id"]))
    elif action == "embed-job":
        await embed_job(services, organization_id, UUID(payload["job_id"]))


async def give_up(
    services: DocumentServices, organization_id: UUID, payload: dict[str, Any]
) -> None:
    """After the last retry: the document is marked failed, so it can be retried by hand."""
    if payload.get("action", "process") == "process":
        async with services.db.tenant(organization_id) as session:
            document = await session.get(Document, UUID(payload["document_id"]))
            if document is not None and document.status not in ("parsed", "quarantined"):
                document.status, document.error_code = "failed", "retries-exhausted"
