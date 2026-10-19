"""Resume upload, candidates and applications over HTTP (SP-04b Task 8). Who may call each route
is the authorisation matrix's job; these check what the routes do."""

import zipfile
from collections.abc import Awaitable, Callable, Sequence
from io import BytesIO
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from hirevion_core.ai import build_ai
from hirevion_core.ai.mock import MockLLM
from hirevion_core.ai.settings import AiSettings
from hirevion_core.ai.types import ChatMessage
from hirevion_core.db.session import Database
from hirevion_core.documents.pipeline import DocumentServices, process_document
from hirevion_core.documents.scan import FakeScanner
from hirevion_core.storage.paths import BlobPath, safe_filename

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]

ASHA = (
    "Asha Rao\nasha.rao@example.test | +91 98765 43210 | Pune\n\nSkills\nPython\n\n"
    "Experience\nSenior Engineer, Acme Software (2020 - present)\n"
)
RAVI = "Ravi Kumar\nravi.kumar@example.test\n\nSkills\nGo\n"


def answer(messages: Sequence[ChatMessage]) -> Any:
    def quoted(value: str) -> dict[str, str]:
        return {"value": value, "quote": value}

    if "Ravi Kumar" in messages[-1]["content"]:
        return {
            "name": quoted("Ravi Kumar"),
            "email": quoted("ravi.kumar@example.test"),
            "skills": [{"name": "Go", "quote": "Go"}],
        }
    return {
        "name": quoted("Asha Rao"),
        "email": quoted("asha.rao@example.test"),
        "location": quoted("Pune"),
        "skills": [{"name": "Python", "quote": "Python"}],
        "positions": [
            {
                "company": "Acme Software",
                "title": "Senior Engineer",
                "current": True,
                "quote": "Senior Engineer, Acme Software",
            }
        ],
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

    def download_url(
        self, organization_id: UUID, path: BlobPath, expires: Any = None, filename: Any = None
    ) -> str:
        if filename is not None:
            safe_filename(filename)  # the real service refuses a name it can't put in a header
        return f"https://storage.test/{path}?download={filename}"


@pytest.fixture
def blobs(api: FastAPI) -> MemoryBlobs:
    store = MemoryBlobs()
    api.state.storage = store
    return store


@pytest.fixture
def services(app_db: Database, blobs: MemoryBlobs) -> DocumentServices:
    ai = build_ai(AiSettings(profile="mock"), app_db)
    assert isinstance(ai.llm, MockLLM)
    ai.llm.scripted["resume.parse"] = answer
    return DocumentServices(db=app_db, blobs=blobs, scanner=FakeScanner(), ai=ai)


@pytest.fixture
async def acme(make_organization: MakeOrganization) -> UUID:
    return await make_organization("Acme")


@pytest.fixture
async def recruiter(signed_in, acme: UUID, make_user, blobs: MemoryBlobs) -> AsyncClient:
    return await signed_in(acme, await make_user(acme, roles=["recruiter"]))


async def new_job(client: AsyncClient) -> str:
    created = await client.post("/api/v1/jobs", json={"title": "Engineer"})
    return str(created.json()["id"])


async def upload(client: AsyncClient, job_id: str, name: str, data: bytes) -> dict[str, Any]:
    answer_ = await client.post(
        f"/api/v1/jobs/{job_id}/resumes", files={"file": (name, data, "application/octet-stream")}
    )
    assert answer_.status_code == 202, answer_.text
    return dict(answer_.json())


async def test_uploaded_resumes_become_candidates_of_the_job(
    recruiter: AsyncClient, services: DocumentServices, acme: UUID
) -> None:
    job_id = await new_job(recruiter)
    bundle = BytesIO()
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("asha.txt", ASHA)
        archive.writestr("ravi.txt", RAVI)
    zipped = await upload(recruiter, job_id, "batch.zip", bundle.getvalue())
    assert (zipped["kind"], zipped["status"]) == ("archive", "uploaded")

    await process_document(services, acme, UUID(zipped["id"]))
    entries = (
        await recruiter.get(f"/api/v1/jobs/{job_id}/resumes", params={"parent_id": zipped["id"]})
    ).json()["items"]
    assert sorted(entry["filename"] for entry in entries) == ["asha.txt", "ravi.txt"]
    for entry in entries:
        await process_document(services, acme, UUID(entry["id"]))

    listed = (await recruiter.get(f"/api/v1/jobs/{job_id}/resumes")).json()["items"]
    parsed = {item["filename"]: item for item in listed}
    assert parsed["batch.zip"]["flags"]["entries"] == 2
    assert parsed["asha.txt"]["candidate"]["name"] == "Asha Rao"

    applications = (await recruiter.get(f"/api/v1/jobs/{job_id}/applications")).json()
    assert sorted(a["candidate"]["name"] for a in applications["items"]) == [
        "Asha Rao",
        "Ravi Kumar",
    ]
    asha = next(a for a in applications["items"] if a["candidate"]["name"] == "Asha Rao")
    assert asha["stage"] == "parsed"
    assert asha["candidate"]["headline"] == "Senior Engineer at Acme Software"
    assert asha["candidate"]["skills"] == ["Python"]


async def test_a_candidate_reads_with_evidence_applications_and_resumes(
    recruiter: AsyncClient, services: DocumentServices, acme: UUID
) -> None:
    job_id = await new_job(recruiter)
    document = await upload(recruiter, job_id, "asha.txt", ASHA.encode())
    await process_document(services, acme, UUID(document["id"]))

    found = (await recruiter.get("/api/v1/candidates", params={"q": "asha.rao@"})).json()
    [summary] = found["items"]
    candidate = (await recruiter.get(f"/api/v1/candidates/{summary['id']}")).json()
    assert candidate["email"] == "asha.rao@example.test"
    assert candidate["profile"]["positions"][0]["quote"] == "Senior Engineer, Acme Software"
    assert candidate["profile"]["positions"][0]["page"] == 1
    assert [(a["job_id"], a["job_reference"], a["stage"]) for a in candidate["applications"]] == [
        (job_id, "JOB-0001", "parsed")
    ]
    assert [d["filename"] for d in candidate["documents"]] == ["asha.txt"]

    by_job = (await recruiter.get("/api/v1/candidates", params={"job_id": job_id})).json()
    assert [c["id"] for c in by_job["items"]] == [summary["id"]]


async def test_a_resume_downloads_through_a_signed_link(
    recruiter: AsyncClient, services: DocumentServices, acme: UUID
) -> None:
    job_id = await new_job(recruiter)
    document = await upload(recruiter, job_id, "asha.txt", ASHA.encode())
    await process_document(services, acme, UUID(document["id"]))
    answer_ = await recruiter.get(
        f"/api/v1/documents/{document['id']}/download", follow_redirects=False
    )
    assert answer_.status_code == 307
    assert answer_.headers["location"].startswith("https://storage.test/")
    assert "download=asha.txt" in answer_.headers["location"]


@pytest.mark.parametrize(
    ("name", "offered"),
    [
        ("Asha Rao - Résumé (1).txt", "Asha_Rao_-_Resume_1.txt"),
        ("résumé.txt", "resume.txt"),
        ("简历.txt", "resume.txt"),
        ("...", "resume"),
    ],
)
async def test_a_resume_with_an_ordinary_file_name_downloads(
    recruiter: AsyncClient, services: DocumentServices, acme: UUID, name: str, offered: str
) -> None:
    job_id = await new_job(recruiter)
    document = await upload(recruiter, job_id, name, ASHA.encode())
    await process_document(services, acme, UUID(document["id"]))
    answer_ = await recruiter.get(
        f"/api/v1/documents/{document['id']}/download", follow_redirects=False
    )
    assert answer_.status_code == 307
    assert answer_.headers["location"].endswith(f"download={offered}")


async def test_a_file_that_has_not_been_scanned_cannot_be_downloaded(
    recruiter: AsyncClient, services: DocumentServices, acme: UUID
) -> None:
    job_id = await new_job(recruiter)
    document = await upload(recruiter, job_id, "asha.txt", ASHA.encode())
    waiting = await recruiter.get(
        f"/api/v1/documents/{document['id']}/download", follow_redirects=False
    )
    assert (waiting.status_code, waiting.json()["code"]) == (409, "not-scanned")
    bundle = BytesIO()
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("asha.txt", ASHA)
    zipped = await upload(recruiter, job_id, "batch.zip", bundle.getvalue())
    await process_document(services, acme, UUID(zipped["id"]))  # opened, never scanned whole
    container = await recruiter.get(
        f"/api/v1/documents/{zipped['id']}/download", follow_redirects=False
    )
    assert (container.status_code, container.json()["code"]) == (409, "not-scanned")


async def test_unsupported_files_are_refused_with_a_reason(recruiter: AsyncClient) -> None:
    job_id = await new_job(recruiter)
    refused = await recruiter.post(
        f"/api/v1/jobs/{job_id}/resumes",
        files={"file": ("song.mp3", b"ID3\x04\x00\x00binary\x00", "audio/mpeg")},
    )
    assert (refused.status_code, refused.json()["code"]) == (422, "unsupported-type")
    assert refused.json()["errors"][0]["pointer"] == "#/file"


async def test_a_hiring_manager_reads_but_cannot_upload_or_retry(
    signed_in, acme: UUID, make_user, recruiter: AsyncClient
) -> None:
    job_id = await new_job(recruiter)
    document = await upload(recruiter, job_id, "asha.txt", ASHA.encode())
    manager = await signed_in(acme, await make_user(acme, roles=["hiring_manager"]))
    assert (await manager.get(f"/api/v1/jobs/{job_id}/resumes")).status_code == 200
    retry = await manager.post(f"/api/v1/documents/{document['id']}/retry")
    assert (retry.status_code, retry.json()["code"]) == (403, "forbidden")
