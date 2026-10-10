"""A reviewer's playback of an interview's recordings (SP-12): read-only URLs that expire in five
minutes, the assembled file once it exists and the segments until then, the resource scope, and
the audit entry for every viewing (PRD §97)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_api.app import create_app
from hirevion_api.settings import ApiSettings
from hirevion_core.db.session import Database
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.models import Recording, RecordingSegment
from hirevion_core.storage.paths import BlobPath
from hirevion_core.storage.service import StorageService, ensure_storage, load_storage_settings
from hirevion_interview_simulator.seed import Seeded, seed_interview

pytestmark = pytest.mark.db

ORIGIN = "https://app.hirevion.localhost"
IDENTITY = IdentitySettings(hibp_enabled=False, web_origin=ORIGIN)
MakeOrganization = Callable[[str], Awaitable[UUID]]
T0 = datetime(2026, 10, 12, 5, 0, 0, tzinfo=UTC)


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
        storage=storage,
    )


async def interview_with_recordings(
    app_db: Database,
    admin_engine: AsyncEngine,
    storage: StorageService,
    make_organization: MakeOrganization,
    make_user: Any,
) -> tuple[Seeded, UUID]:
    org = await make_organization("Acme")
    recruiter = await make_user(org, roles=["recruiter"])
    seed = await seed_interview(
        admin_engine,
        app_db,
        org,
        recruiter,
        password="a long simulated passphrase",
        settings=IDENTITY,
    )
    interview = seed.interview_id
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE interviews SET status = 'completed', started_at = :at WHERE id = :id"),
            {"at": T0, "id": interview},
        )

    async def stored(track: str, name: str, data: bytes, **fields: Any) -> BlobPath:
        folder = "audio" if track == "mic" else track.split("-")[0]
        path = BlobPath(org, f"interviews/{interview}/{folder}/{name}")
        await storage.put(path, data, "application/octet-stream")
        return path

    async with app_db.tenant(org) as session:
        # camera: not assembled yet, two acknowledged segments and one still being uploaded.
        for seq, state in ((0, "acknowledged"), (1, "acknowledged"), (2, "requested")):
            data = f"camera-{seq}".encode()
            path = await stored("camera", f"camera-{seq:06d}.webm", data)
            session.add(
                RecordingSegment(
                    organization_id=org,
                    interview_id=interview,
                    track="camera",
                    seq=seq,
                    started_at=T0 + timedelta(seconds=10 * seq),
                    duration_ms=10_000,
                    bytes=len(data),
                    sha256=hashlib.sha256(data).hexdigest(),
                    container="webm",
                    codec="vp8",
                    blob_path=str(path),
                    state=state,
                )
            )
        session.add(
            Recording(
                organization_id=org,
                interview_id=interview,
                track="camera",
                status="assembly-pending",
            )
        )
        # screen-1: assembled.
        whole = b"the whole screen recording"
        file_path = await stored("screen-1", "screen-1-full.mp4", whole)
        timeline_path = await stored(
            "screen-1", "screen-1-timeline.json", json.dumps({"version": 1}).encode()
        )
        session.add(
            Recording(
                organization_id=org,
                interview_id=interview,
                track="screen-1",
                status="assembled",
                container="mp4",
                blob_path=str(file_path),
                timeline_path=str(timeline_path),
                assembled_bytes=len(whole),
                assembled_sha256=hashlib.sha256(whole).hexdigest(),
                duration_ms=30_000,
                gaps=[
                    {
                        "from_seq": 2,
                        "to_seq": 2,
                        "from_time": T0.isoformat(),
                        "to_time": None,
                        "reason": "missing",
                    }
                ],
            )
        )
    return seed, recruiter


async def test_a_recruiter_plays_back_the_file_or_the_segments(
    app_db: Database,
    admin_engine: AsyncEngine,
    storage: StorageService,
    make_organization: MakeOrganization,
    make_user: Any,
    signed_in: Any,
) -> None:
    seed, recruiter = await interview_with_recordings(
        app_db, admin_engine, storage, make_organization, make_user
    )
    browser = await signed_in(seed.organization_id, recruiter)
    answer = await browser.get(f"/api/v1/interviews/{seed.interview_id}/recordings")
    assert answer.status_code == 200
    body = answer.json()
    assert body["interview_id"] == str(seed.interview_id)
    assert [t["track"] for t in body["tracks"]] == ["screen-1", "camera"]
    screen, camera = body["tracks"]

    assert screen["status"] == "assembled" and screen["segments"] == []
    assert screen["file"]["container"] == "mp4" and screen["file"]["duration_ms"] == 30_000
    assert screen["gaps"][0]["reason"] == "missing"
    assert camera["status"] == "assembly-pending" and camera["file"] is None
    assert [s["seq"] for s in camera["segments"]] == [0, 1]  # the one still uploading isn't there

    async with httpx.AsyncClient() as http:
        assert (await http.get(screen["file"]["url"])).content == b"the whole screen recording"
        assert (await http.get(screen["timeline_url"])).json() == {"version": 1}
        assert (await http.get(camera["segments"][1]["url"])).content == b"camera-1"
        # A viewing URL reads and cannot write.
        refused = await http.put(
            screen["file"]["url"], content=b"x", headers={"x-ms-blob-type": "BlockBlob"}
        )
        assert refused.status_code in (403, 404)

    # Every URL is read-only and lasts five minutes.
    expires = datetime.fromisoformat(body["expires_at"])
    assert timedelta(minutes=4) < expires - datetime.now(UTC) <= timedelta(minutes=5)
    for url in (screen["file"]["url"], screen["timeline_url"], camera["segments"][0]["url"]):
        query = parse_qs(urlparse(url).query)
        assert query["sp"] == ["r"]
        until = datetime.fromisoformat(query["se"][0].replace("Z", "+00:00"))
        assert until - datetime.now(UTC) <= timedelta(minutes=5, seconds=2)


async def test_every_viewing_is_audited(
    app_db: Database,
    admin_engine: AsyncEngine,
    storage: StorageService,
    make_organization: MakeOrganization,
    make_user: Any,
    signed_in: Any,
) -> None:
    seed, recruiter = await interview_with_recordings(
        app_db, admin_engine, storage, make_organization, make_user
    )
    browser = await signed_in(seed.organization_id, recruiter)
    for _ in range(2):
        assert (
            await browser.get(f"/api/v1/interviews/{seed.interview_id}/recordings")
        ).status_code == 200
    async with admin_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT actor_id, resource_type, details FROM audit_logs "
                    "WHERE action = 'recording.viewed' AND resource_id = :id"
                ),
                {"id": str(seed.interview_id)},
            )
        ).all()
    assert len(rows) == 2
    assert rows[0].actor_id == str(recruiter) and rows[0].resource_type == "interview"
    assert rows[0].details == {"tracks": ["screen-1", "camera"], "files": 1, "segments": 2}


async def test_reviewers_see_only_their_interviews_and_other_organisations_none(
    app_db: Database,
    admin_engine: AsyncEngine,
    storage: StorageService,
    make_organization: MakeOrganization,
    make_user: Any,
    signed_in: Any,
) -> None:
    seed, _ = await interview_with_recordings(
        app_db, admin_engine, storage, make_organization, make_user
    )
    org = seed.organization_id
    path = f"/api/v1/interviews/{seed.interview_id}/recordings"
    reviewer = await make_user(org, roles=["interviewer"])
    stranger = await make_user(await make_organization("Globex"), roles=["recruiter"])

    outsider = await signed_in(org, reviewer)
    assert (await outsider.get(path)).status_code == 404  # not one of its reviewers
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO interview_reviewers (organization_id, interview_id, user_id) "
                "VALUES (:org, :iv, :user)"
            ),
            {"org": org, "iv": seed.interview_id, "user": reviewer},
        )
    assert (await outsider.get(path)).status_code == 200

    other_org = await signed_in((await admin_user_org(admin_engine, stranger)), stranger)
    answer = await other_org.get(path)
    assert answer.status_code == 404 and answer.json()["code"] == "interview-not-found"


async def admin_user_org(admin_engine: AsyncEngine, user: UUID) -> UUID:
    async with admin_engine.connect() as conn:
        found = await conn.scalar(
            text("SELECT organization_id FROM users WHERE id = :id"), {"id": user}
        )
    assert found is not None
    return UUID(str(found))
