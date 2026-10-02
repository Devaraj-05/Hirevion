"""The job-description pipeline: intake, scan, text, extraction with verified quotes, embedding,
and the documents stream consumer (SP-04a Task 5)."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import pytest
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.access.actor import Actor
from hirevion_core.access.errors import Conflict
from hirevion_core.ai import AiServices, build_ai
from hirevion_core.ai.mock import MockLLM
from hirevion_core.ai.settings import AiSettings
from hirevion_core.ai.types import AiUnavailable
from hirevion_core.db.session import Database
from hirevion_core.documents import intake
from hirevion_core.documents.consumer import DOCUMENTS_STREAM, DocumentConsumer
from hirevion_core.documents.pipeline import DocumentServices, handle_event, process_document
from hirevion_core.documents.scan import FakeScanner, ScanResult, ScanUnavailable
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.jobs import jobs
from hirevion_core.jobs.jobs import JobChanges
from hirevion_core.models import Document, Job
from hirevion_core.outbox import OutboxRelay
from hirevion_core.storage.paths import BlobPath

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]

JD = (
    "Senior Python Engineer\n\nResponsibilities\n- Design and build REST APIs\n"
    "- Mentor engineers\n\nRequirements\n- 5+ years of Python\n- Experience with Kubernetes\n\n"
    "Nice to have\n- Go\n"
)
EXTRACTION: dict[str, Any] = {
    "title": "Senior Python Engineer",
    "required_skills": [
        {"name": "py", "quote": "5+ years of Python"},
        {"name": "k8s", "quote": "Experience with Kubernetes"},
        {"name": "Rust", "quote": "deep Rust expertise"},  # made up: not in the text
    ],
    "preferred_skills": [{"name": "Go", "quote": "Go"}],
    "experience_min": 5,
    "experience_max": None,
    "responsibilities": [
        {"text": "Design and build REST APIs", "quote": "Design and build REST APIs"},
        {"text": "Mentor engineers", "quote": "Mentor engineers"},
    ],
    "qualifications": [],
    "domain": [],
    "location": None,
    "work_model": None,
}


class MemoryBlobs:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, path: BlobPath, data: bytes, content_type: str) -> None:
        self.blobs[str(path)] = data

    async def get(self, path: BlobPath) -> bytes:
        return self.blobs[str(path)]

    async def delete(self, path: BlobPath) -> None:
        self.blobs.pop(str(path), None)


class DownScanner:
    async def scan(self, data: bytes) -> ScanResult:
        raise ScanUnavailable("clamd is down")


@pytest.fixture
async def ai(app_db: Database) -> AiServices:
    services = build_ai(AiSettings(profile="mock"), app_db)
    assert isinstance(services.llm, MockLLM)
    services.llm.scripted["jd.extract"] = EXTRACTION
    return services


@pytest.fixture
def blobs() -> MemoryBlobs:
    return MemoryBlobs()


@pytest.fixture
def services(app_db: Database, blobs: MemoryBlobs, ai: AiServices) -> DocumentServices:
    return DocumentServices(db=app_db, blobs=blobs, scanner=FakeScanner(), ai=ai)


@pytest.fixture
async def acme(make_organization: MakeOrganization, make_user) -> Actor:
    organization = await make_organization("Acme")
    user = await make_user(organization, roles=["recruiter"])
    return Actor(user, organization, frozenset(permissions_for(["recruiter"])))


async def new_job(app_db: Database, actor: Actor) -> Job:
    async with app_db.tenant(actor.organization_id) as session:
        return await jobs.create_job(session, actor, JobChanges(title="Engineer"))


async def document(app_db: Database, actor: Actor, document_id: UUID) -> Document:
    async with app_db.tenant(actor.organization_id) as session:
        return await session.get_one(Document, document_id)


async def test_a_pasted_description_is_parsed_with_verified_quotes(
    app_db: Database, admin_engine: AsyncEngine, services: DocumentServices, acme: Actor
) -> None:
    job = await new_job(app_db, acme)
    async with app_db.tenant(acme.organization_id) as session:
        submitted = await intake.submit_jd_text(session, acme, job.id, JD)
    assert submitted.status == "uploaded"

    await process_document(services, acme.organization_id, submitted.id)

    parsed = await document(app_db, acme, submitted.id)
    assert parsed.status == "parsed"
    assert parsed.extraction is not None
    assert [s["name"] for s in parsed.extraction["required_skills"]] == ["Python", "Kubernetes"]
    assert parsed.extraction["dropped"] == 1
    assert parsed.extraction["sections"] == ["responsibilities", "requirements", "preferred"]
    async with app_db.tenant(acme.organization_id) as session:
        embedded = await session.get_one(Job, job.id)
        assert embedded.embedding is not None and len(embedded.embedding) == 1536
    async with admin_engine.connect() as conn:
        events = (
            (
                await conn.execute(
                    text("SELECT topic FROM outbox_events WHERE organization_id = :org"),
                    {"org": acme.organization_id},
                )
            )
            .scalars()
            .all()
        )
    assert "documents" in events


async def test_an_uploaded_file_is_typed_stored_and_read(
    app_db: Database,
    blobs: MemoryBlobs,
    services: DocumentServices,
    acme: Actor,
    make_docx: Callable[..., bytes],
) -> None:
    job = await new_job(app_db, acme)
    async with app_db.tenant(acme.organization_id) as session:
        submitted = await intake.submit_jd_file(
            session, acme, job.id, make_docx(*JD.split("\n")), "Senior JD (final).docx", blobs
        )
    assert (submitted.content_type, submitted.filename) == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "Senior JD (final).docx",
    )
    await process_document(services, acme.organization_id, submitted.id)
    parsed = await document(app_db, acme, submitted.id)
    assert parsed.status == "parsed"
    assert parsed.text is not None and "5+ years of Python" in parsed.text


async def test_an_infected_file_is_quarantined_and_never_read(
    app_db: Database,
    blobs: MemoryBlobs,
    services: DocumentServices,
    acme: Actor,
    eicar: bytes,
    ai: AiServices,
) -> None:
    job = await new_job(app_db, acme)
    async with app_db.tenant(acme.organization_id) as session:
        submitted = await intake.submit_jd_file(session, acme, job.id, eicar, "jd.txt", blobs)
    await process_document(services, acme.organization_id, submitted.id)

    quarantined = await document(app_db, acme, submitted.id)
    assert (quarantined.status, quarantined.text) == ("quarantined", None)
    assert quarantined.flags["signature"] == "Eicar-Test-Signature"
    assert all(key.split("/")[1] == "quarantine" for key in blobs.blobs)
    assert isinstance(ai.llm, MockLLM) and ai.llm.calls == 0


async def test_outages_are_retried_and_bad_files_fail(
    app_db: Database, blobs: MemoryBlobs, services: DocumentServices, acme: Actor, ai: AiServices
) -> None:
    job = await new_job(app_db, acme)
    async with app_db.tenant(acme.organization_id) as session:
        scanned = await intake.submit_jd_file(
            session, acme, job.id, b"plain JD text", "a.txt", blobs
        )
        broken = await intake.submit_jd_file(
            session, acme, job.id, b"%PDF-1.4\nnot really a pdf", "b.pdf", blobs
        )
        pasted = await intake.submit_jd_text(session, acme, job.id, JD)

    down = DocumentServices(db=app_db, blobs=blobs, scanner=DownScanner(), ai=ai)
    with pytest.raises(ScanUnavailable):
        await process_document(down, acme.organization_id, scanned.id)
    assert (await document(app_db, acme, scanned.id)).status == "scanning"

    await process_document(services, acme.organization_id, broken.id)
    failed = await document(app_db, acme, broken.id)
    assert (failed.status, failed.error_code) == ("failed", "unreadable")

    assert isinstance(ai.llm, MockLLM)
    ai.llm.failures.append(AiUnavailable("Gemini is busy"))
    with pytest.raises(AiUnavailable):
        await process_document(services, acme.organization_id, pasted.id)
    await process_document(services, acme.organization_id, pasted.id)
    assert (await document(app_db, acme, pasted.id)).status == "parsed"


async def test_a_failed_document_can_be_retried(
    app_db: Database, blobs: MemoryBlobs, services: DocumentServices, acme: Actor
) -> None:
    job = await new_job(app_db, acme)
    async with app_db.tenant(acme.organization_id) as session:
        broken = await intake.submit_jd_file(
            session, acme, job.id, b"%PDF-1.4\nnot really a pdf", "b.pdf", blobs
        )
    await process_document(services, acme.organization_id, broken.id)
    async with app_db.tenant(acme.organization_id) as session:
        retried = await intake.retry_document(session, acme, broken.id)
    assert (retried.status, retried.error_code) == ("uploaded", None)

    # Only a failed document goes round again.
    async with app_db.tenant(acme.organization_id) as session:
        pasted = await intake.submit_jd_text(session, acme, job.id, JD)
    await process_document(services, acme.organization_id, pasted.id)
    with pytest.raises(Conflict) as refusal:
        async with app_db.tenant(acme.organization_id) as session:
            await intake.retry_document(session, acme, pasted.id)
    assert refusal.value.code == "not-retryable"


async def test_the_consumer_processes_each_event_once(
    app_db: Database,
    valkey: Redis,
    relay_db: Database,
    empty_outbox: None,
    services: DocumentServices,
    acme: Actor,
) -> None:

    job = await new_job(app_db, acme)
    async with app_db.tenant(acme.organization_id) as session:
        submitted = await intake.submit_jd_text(session, acme, job.id, JD)
    await OutboxRelay(relay_db, valkey).run_once()
    # Published twice (the outbox delivers at least once): processed once.
    raw: Any = await valkey.xrange(DOCUMENTS_STREAM)
    _, fields = raw[0]
    await valkey.xadd(DOCUMENTS_STREAM, fields)

    processed: list[str] = []

    async def handle(organization_id: UUID, payload: dict[str, Any]) -> None:
        processed.append(payload["document_id"])
        await handle_event(services, organization_id, payload)

    consumer = DocumentConsumer(valkey, handle, group=f"test-{acme.organization_id.hex[-8:]}")
    assert await consumer.run_once() == 1
    assert processed == [str(submitted.id)]
    assert (await document(app_db, acme, submitted.id)).status == "parsed"
    async with app_db.tenant(acme.organization_id) as session:
        assert (await session.scalars(select(Document.status))).all() == ["parsed"]
