"""The document pipeline (PRD §12, master plan §6.6), run by the `documents` consumer:

    uploaded → scanning → extracting → parsing → parsed      (or quarantined / failed)

Each step saves its status in its own transaction, so the processing view shows progress. An
outage (scanner or AI) leaves the document where it stopped and re-raises, so the consumer tries
again later; a bad file ends `failed` with a reason, and an infected one `quarantined`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select

from hirevion_core.ai import AiServices
from hirevion_core.ai.types import (
    AiBudgetExceeded,
    AiContext,
    AiOutputInvalid,
    AiRequestError,
)
from hirevion_core.db.session import Database
from hirevion_core.documents.files import DocumentRejected, sniff
from hirevion_core.documents.intake import BlobStore
from hirevion_core.documents.jd import extract_jd
from hirevion_core.documents.scan import Scanner
from hirevion_core.documents.sections import detect, normalise
from hirevion_core.documents.text import extract
from hirevion_core.jobs.taxonomy import resolve_skills
from hirevion_core.models import Document, Job, JobSkill
from hirevion_core.storage.paths import BlobPath

# How much of a document's text is embedded (the start says the most).
EMBED_CHARACTERS = 8_000


@dataclass(frozen=True, slots=True)
class DocumentServices:
    db: Database
    blobs: BlobStore
    scanner: Scanner
    ai: AiServices
    scan: bool = True


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


async def process_document(
    services: DocumentServices, organization_id: UUID, document_id: UUID
) -> None:
    async with services.db.tenant(organization_id) as session:
        document = await session.get(Document, document_id)
        if document is None or document.status in ("parsed", "quarantined"):
            return
        document.attempts += 1
        document.status = "scanning" if document.blob_path else "extracting"
        blob_key, kind_of_document, pasted = document.blob_path, document.kind, document.text

    if blob_key is not None:
        path = BlobPath(organization_id, blob_key)
        data = await services.blobs.get(path)
        if services.scan:
            verdict = await services.scanner.scan(data)  # ScanUnavailable: retried later
            if not verdict.clean:
                quarantine = f"quarantine/{blob_key.rsplit('/', 1)[-1]}"
                await services.blobs.put(
                    BlobPath(organization_id, quarantine), data, "application/octet-stream"
                )
                await services.blobs.delete(path)
                await _set(
                    services,
                    organization_id,
                    document_id,
                    status="quarantined",
                    blob_path=quarantine,
                    flags={"signature": verdict.signature},
                )
                return
        await _set(services, organization_id, document_id, status="extracting")
        try:
            extracted = extract(data, sniff(data) or "unknown")
        except DocumentRejected as error:
            await _fail(services, organization_id, document_id, error.code)
            return
        raw, pages = extracted.text, extracted.pages
    else:
        raw, pages = pasted or "", 1

    text, hidden = normalise(raw)
    if not text:
        await _fail(services, organization_id, document_id, "no-text")
        return
    sections = [section.name for section in detect(text)]
    await _set(
        services,
        organization_id,
        document_id,
        status="parsing",
        text=text,
        pages=pages,
        flags={"hidden_characters": hidden},
    )
    if kind_of_document != "jd":
        return  # resumes are parsed by SP-04b's pipeline

    try:
        result = await extract_jd(services.ai.llm, organization_id, text, document_id=document_id)
        vector = await _embed(services, organization_id, "jd.embed", text, str(document_id))
    except (AiOutputInvalid, AiRequestError):
        await _fail(services, organization_id, document_id, "ai-failed")
        return
    except AiBudgetExceeded:
        await _fail(services, organization_id, document_id, "budget-exceeded")
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

        document = await session.get_one(Document, document_id)
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


def profile_text(job: Job, skills: list[JobSkill]) -> str:
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
        text = profile_text(job, skills)
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
