"""A simulator run fills the reports (SP-17 exit criterion): the desktop's answers, proctoring
events and recording segments go through the real API, the evaluation runs, and every section of
PRD §68's proctoring report and §69's interview report holds what the run produced (coding,
which is SP-16's, says so)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_api.app import create_app
from hirevion_api.settings import ApiSettings
from hirevion_core.ai import build_ai
from hirevion_core.ai.settings import AiSettings
from hirevion_core.db.session import Database
from hirevion_core.evaluation.service import evaluate_interview
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.interview_session.media import FakeMedia
from hirevion_core.storage.service import StorageService, ensure_storage, load_storage_settings
from hirevion_interview_simulator.client import DesktopClient
from hirevion_interview_simulator.personas import persona
from hirevion_interview_simulator.run import simulate
from hirevion_interview_simulator.seed import seed_interview
from hirevion_interview_simulator.telemetry import SCRIPT, TRACKS, send_telemetry

pytestmark = pytest.mark.db

BASE = "http://api.hirevion.localhost"
ORIGIN = "https://app.hirevion.localhost"
IDENTITY = IdentitySettings(hibp_enabled=False, web_origin=ORIGIN)
PASSWORD = "a long simulated passphrase"  # noqa: S105 (a test password)


@pytest.fixture
async def storage() -> AsyncIterator[StorageService]:
    settings = load_storage_settings()
    direct = settings.model_copy(update={"storage_public_endpoint": settings.internal_endpoint})
    await ensure_storage(direct, [ORIGIN])
    service = StorageService(direct)
    yield service
    await service.aclose()


@pytest.fixture
def api(app_db: Database, valkey: Redis, storage: StorageService) -> FastAPI:
    return create_app(
        ApiSettings(allowed_origins=ORIGIN, run_workers=False, ip_rate_limit=100_000),
        db=app_db,
        redis=valkey,
        identity=IDENTITY,
        ai=build_ai(AiSettings(profile="mock"), app_db),
        media=FakeMedia(),
        storage=storage,
    )


async def test_a_simulated_interview_populates_every_report_section(
    api: FastAPI,
    signed_in: Any,
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: Any,
    make_user: Any,
) -> None:
    org = await make_organization("Acme")
    recruiter = await make_user(org, roles=["recruiter"])
    seed = await seed_interview(
        admin_engine,
        app_db,
        org,
        recruiter,
        password=PASSWORD,
        settings=IDENTITY,
        text_answers=True,
    )
    interview = str(seed.interview_id)
    # A partial candidate has both strengths and knowledge gaps to report.
    candidate = persona("partial", dict(seed.knowledge))
    sent = []

    async with (
        AsyncClient(
            transport=ASGITransport(app=api, raise_app_exceptions=False), base_url=BASE
        ) as http,
        httpx.AsyncClient() as uploader,
    ):
        desktop = DesktopClient(http, base_url=BASE)
        await desktop.login(seed.email, PASSWORD)

        async def after_start(client: DesktopClient, interview_id: str) -> None:
            sent.append(await send_telemetry(client, interview_id, uploader=uploader))

        report = await simulate(desktop, interview, candidate, after_start=after_start)
    assert report.finished and sent[0].events == len(SCRIPT) and not sent[0].refused
    assert sent[0].segments == 2 * len(TRACKS)

    ai = build_ai(AiSettings(profile="mock"), app_db)
    await evaluate_interview(app_db, ai.llm, org, seed.interview_id)

    client = await signed_in(org, recruiter)
    events = (await client.get(f"/api/v1/proctoring/{interview}")).json()["events"]
    phone = next(e for e in events if e["event"] == "PHONE_DETECTED")
    reviewed = await client.post(
        f"/api/v1/proctoring/{interview}/events/{phone['id']}/review",
        json={"outcome": "confirmed", "reason": "Clearly a phone."},
    )
    assert reviewed.status_code == 200, reviewed.text
    noted = await client.post(
        f"/api/v1/interviews/{interview}/notes", json={"body": "Checked the recording."}
    )
    assert noted.status_code == 201

    proctoring = (await client.get(f"/api/v1/interviews/{interview}/reports/proctoring")).json()
    assert len(proctoring["sections"]) == 14
    assert {s["key"]: s["status"] for s in proctoring["sections"]} == {
        s["key"]: "populated" for s in proctoring["sections"]
    }
    sections = {s["key"]: s for s in proctoring["sections"]}
    face = sections["face_events"]["blocks"][0]["rows"]
    assert [row[1] for row in face] == ["Face not visible"]
    assert sections["object_events"]["blocks"][0]["rows"][0][7].startswith(
        "Confirmed by a reviewer"
    )
    assert (
        "anydesk" in str(sections["process_events"]).lower()
        or sections["process_events"]["blocks"][0]["rows"]
    )
    # The recordings the desktop uploaded are in the camera, microphone and screen sections.
    assert "recording" in str(sections["camera_status"]).lower()
    assert "recording" in str(sections["microphone_status"]).lower()
    assert "recording" in str(sections["screen_status"]).lower()

    interview_report = (
        await client.get(f"/api/v1/interviews/{interview}/reports/interview")
    ).json()
    status = {s["key"]: s["status"] for s in interview_report["sections"]}
    assert len(status) == 13 and status.pop("coding_evaluation") == "pending"
    assert {k: v for k, v in status.items() if v != "populated"} == {}, status

    async with admin_engine.begin() as conn:
        stored = await conn.scalar(
            text("SELECT count(*) FROM recording_segments WHERE interview_id = :i"),
            {"i": seed.interview_id},
        )
    assert stored == 2 * len(TRACKS)
