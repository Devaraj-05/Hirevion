"""Jobs, job descriptions and skills over HTTP (SP-04a Task 6). Who may call each route is the
authorisation matrix's job; these check what the routes do."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func

from hirevion_core.ai import build_ai
from hirevion_core.ai.mock import MockLLM
from hirevion_core.ai.settings import AiSettings
from hirevion_core.db.session import Database
from hirevion_core.documents.pipeline import DocumentServices, process_document
from hirevion_core.documents.scan import FakeScanner
from hirevion_core.models import Department, Document, Team
from hirevion_core.storage.paths import BlobPath

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]

JD = (
    "Senior Python Engineer\n\nResponsibilities\n- Design and build REST APIs\n\n"
    "Requirements\n- 5+ years of Python\n- Experience with Kubernetes\n"
)
EXTRACTION: dict[str, Any] = {
    "title": "Senior Python Engineer",
    "required_skills": [
        {"name": "py", "quote": "5+ years of Python"},
        {"name": "Rust", "quote": "deep Rust expertise"},
    ],
    "preferred_skills": [],
    "experience_min": 5,
    "experience_max": None,
    "responsibilities": [
        {"text": "Design and build REST APIs", "quote": "Design and build REST APIs"}
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


@pytest.fixture
def blobs(api: FastAPI) -> MemoryBlobs:
    store = MemoryBlobs()
    api.state.storage = store
    return store


@pytest.fixture
def services(app_db: Database, blobs: MemoryBlobs) -> DocumentServices:
    ai = build_ai(AiSettings(profile="mock"), app_db)
    assert isinstance(ai.llm, MockLLM)
    ai.llm.scripted["jd.extract"] = EXTRACTION
    return DocumentServices(db=app_db, blobs=blobs, scanner=FakeScanner(), ai=ai)


@pytest.fixture
async def acme(make_organization: MakeOrganization) -> UUID:
    return await make_organization("Acme")


@pytest.fixture
async def recruiter(signed_in, acme: UUID, make_user, blobs: MemoryBlobs) -> AsyncClient:
    return await signed_in(acme, await make_user(acme, roles=["recruiter"]))


async def new_job(client: AsyncClient, **fields: Any) -> dict[str, Any]:
    answer = await client.post("/api/v1/jobs", json={"title": "Engineer", **fields})
    assert answer.status_code == 201, answer.text
    return dict(answer.json())


async def test_creating_reading_and_editing_a_job(recruiter: AsyncClient) -> None:
    job = await new_job(
        recruiter,
        title="Senior Python Engineer",
        work_model="hybrid",
        experience_min="4",
        responsibilities=["Design APIs"],
        skills=[{"name": "py"}, {"name": "JS", "importance": "preferred"}],
    )
    assert (job["reference"], job["status"], job["version"]) == ("JOB-0001", "draft", 1)
    assert [(s["name"], s["importance"]) for s in job["skills"]] == [
        ("Python", "required"),
        ("JavaScript", "preferred"),
    ]
    assert job["recruiter_name"] is not None

    read = (await recruiter.get(f"/api/v1/jobs/{job['id']}")).json()
    assert read["title"] == "Senior Python Engineer"

    edited = await recruiter.patch(f"/api/v1/jobs/{job['id']}", json={"location": "Pune"})
    assert (edited.status_code, edited.json()["location"], edited.json()["version"]) == (
        200,
        "Pune",
        2,
    )
    versions = (await recruiter.get(f"/api/v1/jobs/{job['id']}/versions")).json()
    assert [(v["version"], v["reason"]) for v in versions] == [(1, "created"), (2, "edited")]


async def test_bad_fields_point_at_the_field(recruiter: AsyncClient) -> None:
    answer = await recruiter.post("/api/v1/jobs", json={"title": " "})
    assert answer.status_code == 422
    assert answer.json()["errors"][0]["pointer"] == "#/title"
    unknown = await recruiter.post("/api/v1/jobs", json={"title": "x", "status": "open"})
    assert unknown.status_code == 422


async def test_listing_filters_and_searches(recruiter: AsyncClient) -> None:
    await new_job(recruiter, title="Data Analyst")
    second = await new_job(recruiter, title="Backend Engineer")
    everything = (await recruiter.get("/api/v1/jobs")).json()
    assert [j["title"] for j in everything["items"]] == ["Backend Engineer", "Data Analyst"]
    by_number = (await recruiter.get("/api/v1/jobs", params={"q": "JOB-0002"})).json()
    assert [j["id"] for j in by_number["items"]] == [second["id"]]
    drafts = (await recruiter.get("/api/v1/jobs", params={"status": "open"})).json()
    assert drafts["items"] == []
    page = (await recruiter.get("/api/v1/jobs", params={"limit": 1})).json()
    assert len(page["items"]) == 1 and page["next_cursor"] is not None


async def test_the_lifecycle(recruiter: AsyncClient) -> None:
    job = await new_job(recruiter)
    incomplete = await recruiter.post(f"/api/v1/jobs/{job['id']}/status", json={"status": "open"})
    assert (incomplete.status_code, incomplete.json()["code"]) == (422, "job-incomplete")

    await recruiter.patch(
        f"/api/v1/jobs/{job['id']}",
        json={"description": "We build things.", "skills": [{"name": "Python"}]},
    )
    opened = await recruiter.post(f"/api/v1/jobs/{job['id']}/status", json={"status": "open"})
    assert opened.json()["status"] == "open"
    skipped = await recruiter.post(f"/api/v1/jobs/{job['id']}/status", json={"status": "archived"})
    assert (skipped.status_code, skipped.json()["code"]) == (409, "invalid-transition")


async def test_another_organisations_job_does_not_exist(
    recruiter: AsyncClient, signed_in, make_organization: MakeOrganization, make_user
) -> None:
    globex = await make_organization("Globex")
    other = await signed_in(globex, await make_user(globex, roles=["recruiter"]))
    job = await new_job(other)
    assert (await recruiter.get(f"/api/v1/jobs/{job['id']}")).status_code == 404
    edit = await recruiter.patch(f"/api/v1/jobs/{job['id']}", json={"title": "Mine"})
    assert edit.status_code == 404


async def test_a_pasted_description_is_read_reviewed_and_applied(
    recruiter: AsyncClient, services: DocumentServices, acme: UUID
) -> None:
    job = await new_job(recruiter)
    assert (await recruiter.get(f"/api/v1/jobs/{job['id']}/jd")).status_code == 404

    submitted = await recruiter.post(f"/api/v1/jobs/{job['id']}/jd", data={"text": JD})
    assert (submitted.status_code, submitted.json()["status"]) == (202, "uploaded")
    early = await recruiter.post(
        f"/api/v1/jobs/{job['id']}/jd/apply",
        json={"document_id": submitted.json()["id"]},
    )
    assert (early.status_code, early.json()["code"]) == (409, "not-parsed")

    await process_document(services, acme, UUID(submitted.json()["id"]))
    review = (await recruiter.get(f"/api/v1/jobs/{job['id']}/jd")).json()
    assert review["status"] == "parsed"
    assert [s["name"] for s in review["extraction"]["required_skills"]] == ["Python"]
    assert review["extraction"]["dropped"] == 1
    assert "5+ years of Python" in review["text"]

    applied = await recruiter.post(
        f"/api/v1/jobs/{job['id']}/jd/apply",
        json={
            "document_id": review["id"],
            "title": "Senior Python Engineer",
            "skills": [{"name": "Python"}],
            "responsibilities": ["Design and build REST APIs"],
        },
    )
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert (body["title"], body["jd_document_id"]) == ("Senior Python Engineer", review["id"])
    assert body["description"].startswith("Senior Python Engineer")
    versions = (await recruiter.get(f"/api/v1/jobs/{job['id']}/versions")).json()
    assert versions[-1]["reason"] == "jd-applied"


async def test_an_uploaded_description_file(
    recruiter: AsyncClient, blobs: MemoryBlobs, make_docx: Callable[..., bytes]
) -> None:
    job = await new_job(recruiter)
    docx = make_docx(*JD.split("\n"))
    answer = await recruiter.post(
        f"/api/v1/jobs/{job['id']}/jd",
        files={"file": ("Senior JD.docx", docx, "application/octet-stream")},
    )
    assert answer.status_code == 202, answer.text
    assert (answer.json()["filename"], answer.json()["size"]) == ("Senior JD.docx", len(docx))
    assert len(blobs.blobs) == 1

    image = await recruiter.post(
        f"/api/v1/jobs/{job['id']}/jd",
        files={"file": ("jd.png", b"\x89PNG\r\n\x1a\n" + b"0" * 64, "image/png")},
    )
    assert (image.status_code, image.json()["code"]) == (422, "unsupported-type")
    assert image.json()["errors"][0]["pointer"] == "#/file"

    neither = await recruiter.post(f"/api/v1/jobs/{job['id']}/jd", data={})
    assert (neither.status_code, neither.json()["code"]) == (422, "description-required")


async def test_a_failed_description_can_be_retried(
    recruiter: AsyncClient, services: DocumentServices, acme: UUID, app_db: Database
) -> None:
    job = await new_job(recruiter)
    broken = await recruiter.post(
        f"/api/v1/jobs/{job['id']}/jd",
        files={"file": ("b.pdf", b"%PDF-1.4\nnot really a pdf", "application/pdf")},
    )
    document_id = UUID(broken.json()["id"])
    await process_document(services, acme, document_id)
    failed = (await recruiter.get(f"/api/v1/jobs/{job['id']}/jd")).json()
    assert (failed["status"], failed["error_code"]) == ("failed", "unreadable")

    retried = await recruiter.post(f"/api/v1/documents/{document_id}/retry")
    assert (retried.status_code, retried.json()["status"]) == (200, "uploaded")
    again = await recruiter.post(f"/api/v1/documents/{document_id}/retry")
    assert (again.status_code, again.json()["code"]) == (409, "not-retryable")
    async with app_db.tenant(acme) as session:
        assert (await session.get_one(Document, document_id)).error_code is None


async def test_skills_are_suggested(recruiter: AsyncClient) -> None:
    answer = (await recruiter.get("/api/v1/skills", params={"q": "kube"})).json()
    assert answer[0]["name"] == "Kubernetes"
    assert (await recruiter.get("/api/v1/skills", params={"q": " "})).json() == []


async def test_the_form_choices(
    signed_in, acme: UUID, make_user, blobs: MemoryBlobs, app_db: Database
) -> None:
    user = await make_user(acme, roles=["recruiter"])
    client = await signed_in(acme, user)
    async with app_db.tenant(acme) as session:
        department = Department(organization_id=acme, name="Engineering")
        session.add(department)
        await session.flush()
        session.add(Team(organization_id=acme, name="Platform", department_id=department.id))
        session.add(Department(organization_id=acme, name="Old", archived_at=func.now()))
    choices = (await client.get("/api/v1/jobs/choices")).json()
    assert [d["name"] for d in choices["departments"]] == ["Engineering"]
    assert [t["name"] for t in choices["teams"]] == ["Platform"]
    assert str(user) in [p["id"] for p in choices["people"]]


async def test_uploads_need_blob_storage(signed_in, acme: UUID, make_user) -> None:
    client = await signed_in(acme, await make_user(acme, roles=["recruiter"]))
    job = await new_job(client)
    answer = await client.post(
        f"/api/v1/jobs/{job['id']}/jd",
        files={"file": ("jd.txt", b"We need a Go developer.", "text/plain")},
    )
    assert (answer.status_code, answer.json()["code"]) == (503, "storage-unavailable")
