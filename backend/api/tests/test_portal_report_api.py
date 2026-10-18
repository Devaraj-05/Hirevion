"""The portal's report page (SP-17; PRD §99, ADR-0022): a candidate sees only what the organisation
allows and a recruiter released, as it read when released; internal reports never reach the
portal; a PDF of it is rendered once and every download is audited."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_api.app import create_app
from hirevion_api.settings import ApiSettings
from hirevion_core.db.session import Database
from hirevion_core.storage.service import StorageService, ensure_storage, load_storage_settings

from .test_portal_api import (  # noqa: F401
    IDENTITY,
    ORIGIN,
    PORTAL,
    portal,
    post,
    signed_in_candidate,
)
from .test_reports_api import FakeRenderer

pytestmark = pytest.mark.db


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
def app(
    app_db: Database, valkey: Redis, storage: StorageService, renderer: FakeRenderer
) -> FastAPI:
    return create_app(
        ApiSettings(
            allowed_origins=ORIGIN, portal_origins=PORTAL, run_workers=False, ip_rate_limit=100_000
        ),
        db=app_db,
        redis=valkey,
        identity=IDENTITY,
        storage=storage,
        pdf=renderer,
    )


@pytest.fixture
def api(app: FastAPI) -> FastAPI:
    """The recruiter fixtures (`signed_in`) use the same app as the portal's clients."""
    return app


async def finish(admin_engine: AsyncEngine, interview_id: UUID) -> None:
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE interviews SET status = 'completed', "
                "started_at = now() - interval '1 hour', "
                "completed_at = now(), ended_at = now() WHERE id = :id"
            ),
            {"id": interview_id},
        )


async def audited(admin_engine: AsyncEngine, org: UUID, action: str) -> list[dict[str, Any]]:
    async with admin_engine.begin() as conn:
        rows = await conn.execute(
            text(
                "SELECT details, actor_type, actor_id FROM audit_logs "
                "WHERE organization_id = :o AND action = :a ORDER BY seq"
            ),
            {"o": org, "a": action},
        )
        return [{**dict(r.details), "_type": r.actor_type, "_actor": r.actor_id} for r in rows]


async def test_the_candidate_sees_a_report_only_after_a_recruiter_releases_it(
    portal: Any,  # noqa: F811
    signed_in: Any,
    app_db: Database,
    admin_engine: AsyncEngine,
    renderer: FakeRenderer,
    make_organization: Any,
    make_hiring: Any,
) -> None:
    org = await make_organization("Acme")
    candidate, hiring, interview_id, email = await signed_in_candidate(
        portal, app_db, admin_engine, make_hiring, org
    )
    await finish(admin_engine, interview_id)
    recruiter = await signed_in(org, hiring.recruiter_id)
    path = f"/api/v1/interviews/{interview_id}/candidate-report"

    # Nothing is shown before a release, even though the recruiter has a draft.
    assert (await candidate.get("/api/v1/portal/report")).json() == {"reports": []}
    draft = await recruiter.put(
        path,
        json={
            "items": {
                "next_step": {"text": "We will email you by Friday.", "include": True},
                "technical_feedback": {"text": "Study indexing.", "include": True},
            }
        },
    )
    assert draft.status_code == 200
    assert (await candidate.get("/api/v1/portal/report")).json() == {"reports": []}

    released = await recruiter.post(f"{path}/approve")
    assert released.status_code == 200
    body = (await candidate.get("/api/v1/portal/report")).json()
    (item,) = body["reports"]
    assert item["interview_id"] == str(interview_id) and item["job_title"] == "Backend Engineer"
    assert [i["key"] for i in item["items"]] == ["completion", "next_step"]
    assert item["items"][1]["text"] == "We will email you by Friday."
    # Technical feedback was included by the recruiter but the organisation doesn't allow it.
    assert "Study indexing" not in str(body)
    # The release is a snapshot: editing the draft later can't change it (it must be withdrawn
    # first), and nothing internal is in what the candidate reads.
    text_of = str(body).lower()
    for internal in ("score", "proctor", "flag", "note", "recommend", email.lower()):
        assert internal not in text_of, internal

    # A PDF of the released items, audited as the candidate's own download.
    first = await candidate.get(f"/api/v1/portal/report/{interview_id}/pdf")
    assert first.status_code == 200 and first.content.startswith(b"%PDF-")
    assert "next_step" in renderer.pages[0] or "We will email you by Friday." in renderer.pages[0]
    assert "CONFIDENTIAL" not in renderer.pages[0]
    again = await candidate.get(f"/api/v1/portal/report/{interview_id}/pdf")
    assert again.status_code == 200 and len(renderer.pages) == 1  # rendered once, then kept
    downloads = await audited(admin_engine, org, "report.downloaded")
    assert [(d["_type"], d["kind"]) for d in downloads] == [("candidate", "candidate_visible")] * 2

    # Withdrawing takes it off the portal and out of reach of the PDF route.
    await recruiter.post(f"{path}/withdraw", json={"reason": "Sent in error"})
    assert (await candidate.get("/api/v1/portal/report")).json() == {"reports": []}
    assert (await candidate.get(f"/api/v1/portal/report/{interview_id}/pdf")).status_code == 404


async def test_another_candidate_cant_read_or_download_it(
    portal: Any,  # noqa: F811
    signed_in: Any,
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: Any,
    make_hiring: Any,
) -> None:
    org = await make_organization("Acme")
    _, hiring, interview_id, _ = await signed_in_candidate(
        portal, app_db, admin_engine, make_hiring, org
    )
    await finish(admin_engine, interview_id)
    recruiter = await signed_in(org, hiring.recruiter_id)
    await recruiter.post(f"/api/v1/interviews/{interview_id}/candidate-report/approve")
    other, *_ = await signed_in_candidate(portal, app_db, admin_engine, make_hiring, org)
    assert (await other.get("/api/v1/portal/report")).json() == {"reports": []}
    assert (await other.get(f"/api/v1/portal/report/{interview_id}/pdf")).status_code == 404


async def test_the_portal_report_needs_a_portal_session(
    portal: Any,  # noqa: F811
    make_organization: Any,
) -> None:
    client = portal()
    assert (await client.get("/api/v1/portal/report")).status_code == 401
    assert (
        await client.get("/api/v1/portal/report/01a14b24-73e2-75ce-9529-c4fffa034468/pdf")
    ).status_code == 401
