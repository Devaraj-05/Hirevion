"""The reports over HTTP (SP-17; PRD §68, §69, §97, §99): each report as a document of sections, its
PDF, the audit entries for viewing, exporting and downloading, and the candidate-visible report a
recruiter approves."""

from __future__ import annotations

from collections.abc import AsyncIterator
from io import BytesIO
from typing import Any
from uuid import UUID

import pdfplumber
import pytest
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_api.app import create_app
from hirevion_api.settings import ApiSettings
from hirevion_core.db.session import Database
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.reports.pdf import PdfUnavailable, PlaywrightPdfRenderer
from hirevion_core.storage.paths import BlobPath
from hirevion_core.storage.service import StorageService, ensure_storage, load_storage_settings

pytestmark = pytest.mark.db

ORIGIN = "https://app.hirevion.localhost"
IDENTITY = IdentitySettings(hibp_enabled=False, web_origin=ORIGIN)


class FakeRenderer:
    """Stands in for Chromium: the document's text, in a file that starts like a PDF."""

    name = "fake renderer"

    def __init__(self) -> None:
        self.pages: list[str] = []

    async def render(self, html: str, *, footer: str) -> bytes:
        self.pages.append(html)
        return b"%PDF-1.7 fake\n" + html.encode()[:200]


class MissingBrowser:
    name = "no browser"

    async def render(self, html: str, *, footer: str) -> bytes:
        raise PdfUnavailable("no Chromium")


@pytest.fixture
async def storage() -> AsyncIterator[StorageService]:
    settings = load_storage_settings()
    direct = settings.model_copy(update={"storage_public_endpoint": settings.internal_endpoint})
    await ensure_storage(direct, [ORIGIN])
    service = StorageService(direct)
    yield service
    await service.aclose()


@pytest.fixture
def renderer() -> FakeRenderer:
    return FakeRenderer()


@pytest.fixture
def api(
    app_db: Database, valkey: Redis, storage: StorageService, renderer: FakeRenderer
) -> FastAPI:
    return create_app(
        ApiSettings(allowed_origins=ORIGIN, run_workers=False, ip_rate_limit=100_000),
        db=app_db,
        redis=valkey,
        identity=IDENTITY,
        storage=storage,
        pdf=renderer,
    )


async def audited(admin_engine: AsyncEngine, org: UUID, action: str) -> list[dict[str, Any]]:
    async with admin_engine.begin() as conn:
        rows = await conn.execute(
            text(
                "SELECT details, actor_id, resource_id FROM audit_logs "
                "WHERE organization_id = :o AND action = :a ORDER BY seq"
            ),
            {"o": org, "a": action},
        )
        return [{**dict(r.details), "_actor": r.actor_id, "_resource": r.resource_id} for r in rows]


def interview_url(scene: Any, tail: str) -> str:
    return f"/api/v1/interviews/{scene.interview_id}{tail}"


async def test_the_interview_report_has_thirteen_sections_and_viewing_is_audited(
    signed_in: Any,
    admin_engine: AsyncEngine,
    make_organization: Any,
    make_reviewed_interview: Any,
) -> None:
    org = await make_organization("Acme")
    scene, _, _ = await make_reviewed_interview(org)
    client = await signed_in(org, scene.hiring.recruiter_id)
    response = await client.get(interview_url(scene, "/reports/interview"))
    assert response.status_code == 200
    doc = response.json()
    assert doc["kind"] == "interview" and doc["confidential"] is True
    assert len(doc["sections"]) == 13
    assert [s["status"] for s in doc["sections"]].count("populated") == 12
    assert {s["key"]: s["status"] for s in doc["sections"]}["coding_evaluation"] == "pending"
    skills = next(b for b in doc["sections"][4]["blocks"] if b["type"] == "table")
    assert {row[0] for row in skills["rows"]} == {"PostgreSQL", "Python"}
    # Looking again within five minutes is one audit entry, as with the proctoring report.
    await client.get(interview_url(scene, "/reports/interview"))
    entries = await audited(admin_engine, org, "report.viewed")
    assert [(e["kind"], e["_actor"]) for e in entries] == [
        ("interview", str(scene.hiring.recruiter_id))
    ]
    assert entries[0]["_resource"] == str(scene.interview_id)


async def test_the_proctoring_report_has_fourteen_sections_and_follows_the_permission(
    signed_in: Any,
    admin_engine: AsyncEngine,
    make_organization: Any,
    make_reviewed_interview: Any,
    make_user: Any,
) -> None:
    org = await make_organization("Acme")
    scene, _, _ = await make_reviewed_interview(org)
    recruiter = await signed_in(org, scene.hiring.recruiter_id)
    doc = (await recruiter.get(interview_url(scene, "/reports/proctoring"))).json()
    assert len(doc["sections"]) == 14
    assert {s["status"] for s in doc["sections"]} == {"populated"}
    assert "no single score" in str(doc).lower()
    manager = await signed_in(org, await make_user(org, roles=["hiring_manager"]))
    assert (await manager.get(interview_url(scene, "/reports/proctoring"))).status_code == 200
    # An interviewer reviewing this interview reads its interview report, not its proctoring.
    reviewer = await make_user(org, roles=["interviewer"])
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO interview_reviewers (organization_id, interview_id, user_id) "
                "VALUES (:o, :i, :u)"
            ),
            {"o": org, "i": scene.interview_id, "u": reviewer},
        )
    other = await signed_in(org, reviewer)
    shown = await other.get(interview_url(scene, "/reports/interview"))
    assert shown.status_code == 200
    # The interview report they may read holds no integrity signals, notes or decisions.
    for private in ("Integrity signals", "Phone seen in the camera", "Note added"):
        assert private not in str(shown.json()), private
    denied = await other.get(interview_url(scene, "/reports/proctoring"))
    assert denied.status_code == 403
    # Someone from another organisation finds nothing.
    stranger_org = await make_organization("Globex")
    stranger = await signed_in(stranger_org, await make_user(stranger_org, roles=["recruiter"]))
    assert (await stranger.get(interview_url(scene, "/reports/interview"))).status_code == 404


async def test_the_coding_and_candidate_reports(
    signed_in: Any, make_organization: Any, make_reviewed_interview: Any
) -> None:
    org = await make_organization("Acme")
    scene, _, _ = await make_reviewed_interview(org)
    client = await signed_in(org, scene.hiring.recruiter_id)
    coding = (await client.get(interview_url(scene, "/reports/coding"))).json()
    assert coding["kind"] == "coding" and "SP-16" in str(coding)
    candidate = await client.get(f"/api/v1/candidates/{scene.hiring.candidate_id}/report")
    assert candidate.status_code == 200
    doc = candidate.json()
    assert doc["kind"] == "candidate" and doc["confidential"] is True
    assert len(doc["sections"]) == 11


async def test_exporting_stores_a_pdf_and_downloading_it_is_audited(
    signed_in: Any,
    admin_engine: AsyncEngine,
    storage: StorageService,
    renderer: FakeRenderer,
    make_organization: Any,
    make_reviewed_interview: Any,
) -> None:
    org = await make_organization("Acme")
    scene, _, _ = await make_reviewed_interview(org)
    client = await signed_in(org, scene.hiring.recruiter_id)
    made = await client.post(
        "/api/v1/report-exports",
        json={"kind": "interview", "interview_id": str(scene.interview_id)},
    )
    assert made.status_code == 201, made.text
    export = made.json()
    assert export["kind"] == "interview" and export["renderer"] == "fake renderer"
    assert export["requested_by"] == str(scene.hiring.recruiter_id) and export["bytes"] > 0
    assert "Interview report" in renderer.pages[0] and "Asha Rao" in renderer.pages[0]

    listed = (await client.get(f"/api/v1/report-exports?interview_id={scene.interview_id}")).json()
    assert [item["id"] for item in listed["items"]] == [export["id"]]

    download = await client.get(f"/api/v1/report-exports/{export['id']}/download")
    assert download.status_code == 200 and download.content.startswith(b"%PDF-")
    assert download.headers["content-type"] == "application/pdf"
    assert 'filename="interview-report-IV-0001.pdf"' in download.headers["content-disposition"]
    assert download.headers["cache-control"] == "private, no-store"
    assert [e["kind"] for e in await audited(admin_engine, org, "report.exported")] == ["interview"]
    downloads = await audited(admin_engine, org, "report.downloaded")
    assert len(downloads) == 1 and downloads[0]["export_id"] == export["id"]
    # Downloading again is audited again: the log shows every download.
    await client.get(f"/api/v1/report-exports/{export['id']}/download")
    assert len(await audited(admin_engine, org, "report.downloaded")) == 2

    # A stored file that no longer matches its record is not handed out.
    async with admin_engine.begin() as conn:
        path = await conn.scalar(
            text("SELECT blob_path FROM report_exports WHERE id = :i"), {"i": export["id"]}
        )
    await storage.put(
        BlobPath(org, str(path).split("/", 1)[1]), b"%PDF-tampered", "application/pdf"
    )
    tampered = await client.get(f"/api/v1/report-exports/{export['id']}/download")
    assert tampered.status_code == 404 and tampered.json()["code"] == "export-corrupt"


async def test_who_may_export_and_what_they_may_reach(
    signed_in: Any, make_organization: Any, make_reviewed_interview: Any, make_user: Any
) -> None:
    org = await make_organization("Acme")
    scene, _, _ = await make_reviewed_interview(org)
    body = {"kind": "interview", "interview_id": str(scene.interview_id)}
    interviewer = await signed_in(org, await make_user(org, roles=["interviewer"]))
    assert (await interviewer.post("/api/v1/report-exports", json=body)).status_code == 403
    recruiter = await signed_in(org, scene.hiring.recruiter_id)
    export = (await recruiter.post("/api/v1/report-exports", json=body)).json()
    missing = await recruiter.post("/api/v1/report-exports", json={"kind": "interview"})
    assert missing.status_code == 422 and missing.json()["code"] == "interview-required"
    # Another organisation neither lists nor downloads it.
    other_org = await make_organization("Globex")
    other = await signed_in(other_org, await make_user(other_org, roles=["recruiter"]))
    assert (await other.get(f"/api/v1/report-exports/{export['id']}/download")).status_code == 404
    assert (await other.post("/api/v1/report-exports", json=body)).status_code == 404
    # The candidate-visible report can't be exported before it is released.
    held = await recruiter.post(
        "/api/v1/report-exports",
        json={"kind": "candidate_visible", "interview_id": str(scene.interview_id)},
    )
    assert held.status_code == 409 and held.json()["code"] == "not-released"


async def test_an_export_says_when_there_is_no_browser(
    api: FastAPI, signed_in: Any, make_organization: Any, make_reviewed_interview: Any
) -> None:
    org = await make_organization("Acme")
    scene, _, _ = await make_reviewed_interview(org)
    client = await signed_in(org, scene.hiring.recruiter_id)
    api.state.pdf_renderer = MissingBrowser()
    refused = await client.post(
        "/api/v1/report-exports",
        json={"kind": "proctoring", "interview_id": str(scene.interview_id)},
    )
    assert refused.status_code == 503 and refused.json()["code"] == "pdf-unavailable"
    # The web view still works without it.
    assert (await client.get(interview_url(scene, "/reports/proctoring"))).status_code == 200


async def test_a_real_browser_renders_the_report_a_reviewer_downloads(
    api: FastAPI, signed_in: Any, make_organization: Any, make_reviewed_interview: Any
) -> None:
    org = await make_organization("Acme")
    scene, _, _ = await make_reviewed_interview(org)
    client = await signed_in(org, scene.hiring.recruiter_id)
    api.state.pdf_renderer = PlaywrightPdfRenderer()
    made = await client.post(
        "/api/v1/report-exports",
        json={"kind": "proctoring", "interview_id": str(scene.interview_id)},
    )
    if made.status_code == 503:
        pytest.skip("Chromium isn't installed: run `uv run playwright install chromium`")
    assert made.status_code == 201, made.text
    data = (await client.get(f"/api/v1/report-exports/{made.json()['id']}/download")).content
    with pdfplumber.open(BytesIO(data)) as opened:
        pages = "\n".join(page.extract_text() or "" for page in opened.pages)
    flat = " ".join(pages.split())
    assert "Proctoring report" in flat and "no single score" in flat
    # Table cells wrap, so the text of neighbouring cells interleaves: look for single words.
    assert "Looked" in flat and "monitor" in flat and "false" in flat
    assert "CONFIDENTIAL" in flat


async def test_the_candidate_visible_report_is_drafted_edited_and_released_by_a_recruiter(
    signed_in: Any,
    admin_engine: AsyncEngine,
    make_organization: Any,
    make_reviewed_interview: Any,
    make_user: Any,
) -> None:
    org = await make_organization("Acme")
    scene, _, _ = await make_reviewed_interview(org)
    recruiter = await signed_in(org, scene.hiring.recruiter_id)
    path = interview_url(scene, "/candidate-report")

    first = (await recruiter.get(path)).json()
    assert first["status"] == "none" and first["ready"] is True
    assert [item["key"] for item in first["items"]] == [
        "completion",
        "general_feedback",
        "technical_feedback",
        "coding_feedback",
        "next_step",
    ]
    allowed = {item["key"]: item["allowed"] for item in first["items"]}
    assert allowed == {
        "completion": True,
        "general_feedback": False,
        "technical_feedback": False,
        "coding_feedback": False,
        "next_step": True,
    }
    # A hiring manager reads it but can't release it.
    manager = await signed_in(org, await make_user(org, roles=["hiring_manager"]))
    assert (await manager.get(path)).status_code == 200
    assert (await manager.post(f"{path}/approve")).status_code == 403
    assert (await manager.put(path, json={"items": {}})).status_code == 403

    saved = await recruiter.put(
        path,
        json={
            "items": {
                "next_step": {"text": "We will email you by Friday.", "include": True},
                "general_feedback": {"text": "Clear on databases.", "include": True},
            }
        },
    )
    assert saved.status_code == 200 and saved.json()["status"] == "draft"
    released = (await recruiter.post(f"{path}/approve")).json()
    assert released["status"] == "released" and released["approved_by"] == str(
        scene.hiring.recruiter_id
    )
    assert [item["key"] for item in released["released"]] == ["completion", "next_step"]
    assert released["released"][1]["text"] == "We will email you by Friday."
    assert (await recruiter.put(path, json={"items": {}})).status_code == 409
    assert len(await audited(admin_engine, org, "report.released")) == 1

    withdrawn = await recruiter.post(f"{path}/withdraw", json={"reason": "Sent in error"})
    assert withdrawn.status_code == 200 and withdrawn.json()["status"] == "withdrawn"
    assert withdrawn.json()["released"] == []
    assert len(await audited(admin_engine, org, "report.withdrawn")) == 1


async def test_the_organisation_chooses_the_items_candidates_can_be_shown(
    signed_in: Any, make_organization: Any, make_user: Any
) -> None:
    org = await make_organization("Acme")
    admin = await signed_in(org, await make_user(org, roles=["org_admin"]))
    recruiter = await signed_in(org, await make_user(org, roles=["recruiter"]))
    current = (await recruiter.get("/api/v1/organization/candidate-report")).json()
    assert current["items"]["technical_feedback"] is False
    assert (
        await recruiter.put("/api/v1/organization/candidate-report", json={"items": {}})
    ).status_code == 403
    changed = await admin.put(
        "/api/v1/organization/candidate-report",
        json={"items": {"technical_feedback": True, "next_step": False}},
    )
    assert changed.status_code == 200
    assert changed.json()["items"]["technical_feedback"] is True
    assert changed.json()["items"]["next_step"] is False
    assert changed.json()["items"]["completion"] is True
