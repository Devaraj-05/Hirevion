"""The third eye end to end (SP-13; `docs/api/contracts/third-eye.md`): the desktop pairs, the
phone redeems once and streams, LiveKit's webhooks drive the status, pairing again revokes and
kicks, a locked phone is flagged within 10 s, a required third eye gates `start`, and Egress files
become playable recordings. LiveKit is the fake (`FakeMedia`); the database, Valkey and Azurite
are real."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_api.app import create_app
from hirevion_api.settings import ApiSettings
from hirevion_core.db.session import Database
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.interview_session.media import FakeMedia
from hirevion_core.interview_session.realtime import stream_key
from hirevion_core.models import OutboxEvent, ProctorEvent, Recording, SystemCheckResult
from hirevion_core.proctoring.service import ProctorEngine
from hirevion_core.recordings.playback import playable_tracks
from hirevion_core.storage.service import StorageService, ensure_storage, load_storage_settings
from hirevion_core.third_eye import egress
from hirevion_core.third_eye.settings import ThirdEyeSettings
from hirevion_interview_simulator.client import DesktopClient
from hirevion_interview_simulator.seed import Seeded, seed_interview

pytestmark = pytest.mark.db

BASE = "http://api.hirevion.localhost"
ORIGIN = "https://app.hirevion.localhost"
IDENTITY = IdentitySettings(hibp_enabled=False, web_origin=ORIGIN)
PASSWORD = "a long simulated passphrase"  # noqa: S105 (a test password)
IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
)
MakeOrganization = Callable[[str], Awaitable[UUID]]


@pytest.fixture
def media() -> FakeMedia:
    return FakeMedia()


@pytest.fixture
async def storage() -> AsyncIterator[StorageService]:
    settings = load_storage_settings()
    direct = settings.model_copy(update={"storage_public_endpoint": settings.internal_endpoint})
    await ensure_storage(direct, [ORIGIN])
    service = StorageService(direct)
    yield service
    await service.aclose()


@pytest.fixture
def api(
    app_db: Database, valkey: Redis, media: FakeMedia, storage: StorageService, tmp_path: Path
) -> FastAPI:
    app = create_app(
        ApiSettings(allowed_origins=ORIGIN, run_workers=False, ip_rate_limit=100_000),
        db=app_db,
        redis=valkey,
        identity=IDENTITY,
        storage=storage,
        media=media,
    )
    app.state.third_eye_settings = ThirdEyeSettings(  # type: ignore[call-arg]
        egress_local_dir=tmp_path, egress_container_dir="/out"
    )
    return app


@pytest.fixture
def client(api: FastAPI, client_for: Callable[[FastAPI], AsyncClient]) -> AsyncClient:
    return client_for(api)


class Desk:
    """A signed-in desktop with an interview-session token, and the phone's calls."""

    def __init__(self, client: AsyncClient, desktop: DesktopClient, seed: Seeded) -> None:
        self.client, self.desktop, self.seed = client, desktop, seed
        self.interview = str(seed.interview_id)
        self.org = seed.organization_id

    def call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        return self.desktop.call(
            method, path, json=body, token=self.desktop.session_tokens[self.interview]
        )

    async def pair(self) -> dict[str, Any]:
        issued: Response = await self.call(
            "POST", "/third-eye/pairings", {"interview_id": self.interview}
        )
        assert issued.status_code == 201, issued.text
        return issued.json()  # type: ignore[no-any-return]

    async def redeem(self, token: str) -> Response:
        return await self.client.post(
            "/api/v1/third-eye/redeem", json={"token": token, "device": {"user_agent": IPHONE}}
        )

    async def status(self, pairing_id: str) -> dict[str, Any]:
        answer: Response = await self.call("GET", f"/third-eye/pairings/{pairing_id}")
        assert answer.status_code == 200, answer.text
        return answer.json()  # type: ignore[no-any-return]

    async def webhook(self, kind: str, at: datetime | None = None, **fields: Any) -> None:
        body = {
            "kind": kind,
            "interview_id": self.interview,
            "organization_id": str(self.org),
            "at": (at or datetime.now(UTC)).isoformat(),
            **fields,
        }
        sent = await self.client.post(
            "/api/v1/livekit/webhook",
            content=json.dumps(body),
            headers={"Authorization": "fake-signature"},
        )
        assert sent.status_code == 204, sent.text


def token_of(qr_url: str) -> str:
    return qr_url.split("#t=", 1)[1]


async def make_desk(
    client: AsyncClient,
    admin_engine: AsyncEngine,
    app_db: Database,
    make_organization: MakeOrganization,
    make_user: Any,
    *,
    third_eye: str = "optional",
    status: str | None = None,
    voice: bool = False,
) -> Desk:
    org = await make_organization("Acme")
    recruiter = await make_user(org, roles=["recruiter"])
    seed = await seed_interview(
        admin_engine, app_db, org, recruiter, password=PASSWORD, settings=IDENTITY
    )
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE interviews SET policy = jsonb_set(policy, '{third_eye}', "
                "to_jsonb(CAST(:mode AS text))) WHERE id = :id"
            ),
            {"mode": third_eye, "id": seed.interview_id},
        )
        if third_eye == "required":
            # As assignment pins it for a template that requires the third eye.
            await conn.execute(
                text(
                    "UPDATE interviews SET policy = jsonb_set(policy, '{mandatory_checks}', "
                    "COALESCE(policy->'mandatory_checks', '[]'::jsonb) || '[\"third_eye\"]') "
                    "WHERE id = :id"
                ),
                {"id": seed.interview_id},
            )
        if voice:
            # The simulator answers in text; Egress records a voice interview's audio.
            await conn.execute(
                text(
                    "UPDATE interviews SET policy = jsonb_set(policy, '{answer_mode}', "
                    "'\"voice\"') WHERE id = :id"
                ),
                {"id": seed.interview_id},
            )
        if status is not None:
            await conn.execute(
                text("UPDATE interviews SET status = :status, started_at = now() WHERE id = :id"),
                {"status": status, "id": seed.interview_id},
            )
    desktop = DesktopClient(client, base_url=BASE)
    await desktop.login(seed.email, PASSWORD)
    await desktop.session_token(str(seed.interview_id))
    return Desk(client, desktop, seed)


@pytest.fixture
async def desk(
    client: AsyncClient,
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user: Any,
) -> Desk:
    return await make_desk(client, admin_engine, app_db, make_organization, make_user)


async def stream_types(valkey: Redis, interview: str) -> list[dict[str, Any]]:
    entries = await valkey.xrange(stream_key(UUID(interview)))
    return [json.loads(fields.get(b"event") or fields["event"]) for _, fields in entries]


# The contract.


async def test_the_desktop_pairs_and_the_phone_streams(
    desk: Desk, media: FakeMedia, valkey: Redis
) -> None:
    began = time.monotonic()
    issued = await desk.pair()
    assert set(issued) == {"pairing_id", "qr_url", "expires_at", "status"}
    assert issued["status"] == "issued"
    assert issued["qr_url"].startswith("https://eye.hirevion.localhost/#t=")
    expires = datetime.fromisoformat(issued["expires_at"])
    assert timedelta(minutes=1, seconds=50) < expires - datetime.now(UTC) <= timedelta(minutes=2)
    pairing = issued["pairing_id"]

    joined = await desk.redeem(token_of(issued["qr_url"]))
    assert joined.status_code == 200, joined.text
    body = joined.json()
    assert body["participant_identity"] == f"third-eye-{pairing}"
    assert body["participant_token"] == f"fake-third-eye-{pairing}"
    assert body["livekit_url"] is None  # the page's own origin proxies LiveKit
    assert body["interview"] == {"company": "Acme", "job_title": "Backend Engineer (simulated)"}
    assert body["placement"] == {
        "distance_m": 1.5,
        "angle": "side-rear",
        "show": ["face", "hands", "desk", "screen"],
    }
    assert body["device_token"] and body["device_token"] != token_of(issued["qr_url"])
    lifetime = datetime.fromisoformat(body["expires_at"]) - datetime.now(UTC)
    assert timedelta(minutes=9) < lifetime <= timedelta(minutes=10)
    assert f"iv-{desk.interview}" in media.rooms  # the room exists before the interview starts
    assert (await desk.status(pairing))["status"] == "redeemed"

    await desk.webhook("third_eye_joined", identity=f"third-eye-{pairing}")
    await desk.webhook(
        "third_eye_published",
        identity=f"third-eye-{pairing}",
        track_sid="TR_1",
        width=1280,
        height=720,
    )
    status = await desk.status(pairing)
    elapsed = time.monotonic() - began
    assert status["status"] == "connected" and status["device"] == {"platform": "iOS 17 Safari"}
    assert status["video"] == {"width": 1280, "height": 720, "fps": 15}
    assert status["connected_at"] is not None and status["reconnects"] == 0
    # The server's part of pairing (issue, redeem, connect) is a fraction of the 60 s budget.
    assert elapsed < 5

    await desk.webhook("third_eye_unpublished", identity=f"third-eye-{pairing}")
    await desk.webhook("third_eye_published", identity=f"third-eye-{pairing}", track_sid="TR_2")
    status = await desk.status(pairing)
    assert status["status"] == "connected" and status["reconnects"] == 1
    events = [
        e for e in await stream_types(valkey, desk.interview) if e["type"] == "THIRD_EYE_STATUS"
    ]
    assert [e["data"]["status"] for e in events] == [
        "redeemed",
        "connected",
        "disconnected",
        "reconnected",
    ]


async def test_a_token_is_spent_once_and_expires(desk: Desk, admin_engine: AsyncEngine) -> None:
    issued = await desk.pair()
    token = token_of(issued["qr_url"])
    assert (await desk.redeem(token)).status_code == 200
    again = await desk.redeem(token)
    assert again.status_code == 410 and again.json()["code"] == "token-used"
    unknown = await desk.redeem("x" * 43)
    assert unknown.status_code == 404 and unknown.json()["code"] == "pairing-not-found"

    late = await desk.pair()
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE third_eye_pairings SET expires_at = now() WHERE id = :id"),
            {"id": late["pairing_id"]},
        )
    expired = await desk.redeem(token_of(late["qr_url"]))
    assert expired.status_code == 410 and expired.json()["code"] == "token-expired"
    assert (await desk.status(late["pairing_id"]))["status"] == "expired"


async def test_pairing_again_revokes_and_kicks_the_old_phone(desk: Desk, media: FakeMedia) -> None:
    first = await desk.pair()
    old = (await desk.redeem(token_of(first["qr_url"]))).json()
    identity = old["participant_identity"]
    await desk.webhook("third_eye_published", identity=identity, track_sid="TR_1")

    second = await desk.pair()
    assert (await desk.status(first["pairing_id"]))["status"] == "revoked"
    assert media.removed == [identity]
    refused = await desk.redeem(token_of(first["qr_url"]))
    assert refused.status_code == 410 and refused.json()["code"] == "pairing-revoked"
    rejoin = await desk.client.post(
        "/api/v1/third-eye/rejoin", json={"device_token": old["device_token"]}
    )
    assert rejoin.status_code == 404  # the revoked phone's secret is gone

    # The old phone coming back is removed again and changes nothing.
    await desk.webhook("third_eye_joined", identity=identity)
    assert media.removed == [identity, identity]
    assert (await desk.status(first["pairing_id"]))["status"] == "revoked"

    new = (await desk.redeem(token_of(second["qr_url"]))).json()
    revoked = await desk.call("POST", f"/third-eye/pairings/{second['pairing_id']}/revoke")
    assert revoked.status_code == 204
    assert media.removed[-1] == new["participant_identity"]


async def test_a_phone_rejoins_with_its_device_secret(desk: Desk) -> None:
    issued = await desk.pair()
    joined = (await desk.redeem(token_of(issued["qr_url"]))).json()
    again = await desk.client.post(
        "/api/v1/third-eye/rejoin", json={"device_token": joined["device_token"]}
    )
    assert again.status_code == 200, again.text
    assert again.json()["participant_identity"] == joined["participant_identity"]
    assert again.json()["device_token"] is None


async def test_another_interviews_token_cannot_see_or_revoke_a_pairing(
    desk: Desk,
    client: AsyncClient,
    admin_engine: AsyncEngine,
    app_db: Database,
    make_organization: MakeOrganization,
    make_user: Any,
) -> None:
    issued = await desk.pair()
    other = await make_desk(client, admin_engine, app_db, make_organization, make_user)
    seen = await other.call("GET", f"/third-eye/pairings/{issued['pairing_id']}")
    assert seen.status_code == 404
    wrong = await other.call("POST", "/third-eye/pairings", {"interview_id": desk.interview})
    assert wrong.status_code == 403


# The exit criteria with the interview.


async def test_a_required_third_eye_gates_start_and_a_locked_phone_is_flagged_in_10_s(
    client: AsyncClient,
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user: Any,
    valkey: Redis,
) -> None:
    desk = await make_desk(
        client, admin_engine, app_db, make_organization, make_user, third_eye="required"
    )
    interview = desk.interview
    briefing = await desk.desktop.briefing(interview)
    assert "third_eye" in briefing["mandatory_checks"]
    consent = await desk.desktop.consent(interview, briefing["notice"])

    # The desktop claims a third eye; the server stores what it saw (nothing yet).
    check = await desk.desktop.system_check(interview, briefing["mandatory_checks"])
    assert check["passed"] is False and check["failed_mandatory"] == ["third_eye"]
    refused = await desk.call(
        "POST",
        f"/interviews/{interview}/start",
        {"system_check_id": check["id"], "consent_id": consent["id"]},
    )
    assert refused.status_code == 409

    issued = await desk.pair()
    joined = (await desk.redeem(token_of(issued["qr_url"]))).json()
    await desk.webhook(
        "third_eye_published", identity=joined["participant_identity"], track_sid="TR_1"
    )
    check = await desk.desktop.system_check(interview, briefing["mandatory_checks"])
    assert check["passed"] is True
    async with app_db.tenant(desk.org) as session:
        stored = await session.get_one(SystemCheckResult, UUID(check["id"]))
    third = next(r for r in stored.results if r["check"] == "third_eye")
    assert third == {
        "check": "third_eye",
        "status": "pass",
        "value": "connected",
        "detail": "server-observed: iOS 17 Safari",
    }
    await desk.desktop.start(interview, check["id"], consent["id"])
    opened = await desk.call(
        "POST", "/proctoring/session", {"interview_id": interview, "app_version": "1.4.0"}
    )
    assert opened.status_code == 200, opened.text
    session_id = UUID(opened.json()["proctor_session_id"])

    # Locking the phone: the page unpublishes its camera; LiveKit's webhook arrives at once.
    locked = datetime.now(UTC)
    await desk.webhook("third_eye_unpublished", at=locked, identity=joined["participant_identity"])
    engine = ProctorEngine(app_db, valkey)
    await engine.tick(desk.org, session_id, now=locked + timedelta(seconds=4))
    async with app_db.tenant(desk.org) as session:
        assert (await session.scalars(select(ProctorEvent))).all() == []  # still debouncing
    flagged_at = locked + timedelta(seconds=6)
    await engine.tick(desk.org, session_id, now=flagged_at)
    async with app_db.tenant(desk.org) as session:
        rows = (await session.scalars(select(ProctorEvent))).all()
    assert [(r.event, r.origin) for r in rows] == [("THIRD_EYE_DISCONNECTED", "server")]
    assert (flagged_at - locked) <= timedelta(seconds=10)
    assert rows[0].details["sources"] == ["livekit"]


# Egress.


async def test_egress_records_the_conversation_and_the_third_eye_into_playable_tracks(
    client: AsyncClient,
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user: Any,
    media: FakeMedia,
    api: FastAPI,
    storage: StorageService,
    valkey: Redis,
    tmp_path: Path,
) -> None:
    desk = await make_desk(
        client,
        admin_engine,
        app_db,
        make_organization,
        make_user,
        status="in_progress",
        voice=True,
    )
    await desk.webhook("candidate_joined", identity="candidate-x")
    await desk.webhook("candidate_joined", identity="candidate-x")  # one audio run at a time
    issued = await desk.pair()
    joined = (await desk.redeem(token_of(issued["qr_url"]))).json()
    await desk.webhook(
        "third_eye_published", identity=joined["participant_identity"], track_sid="TR_9"
    )
    assert [(e[0], e[1]) for e in media.egresses] == [("EG_1", "audio"), ("EG_2", "TR_9")]
    org, interview = desk.org, desk.interview
    audio_key = f"{org}/interviews/{interview}/audio/conversation-audio-1-full.mp4"
    eye_key = f"{org}/interviews/{interview}/third-eye/third-eye-1-full.webm"
    assert [e[2].filepath for e in media.egresses] == [f"/out/{audio_key}", f"/out/{eye_key}"]

    for egress_id, key, content in (
        ("EG_1", audio_key, b"audio-bytes" * 100),
        ("EG_2", eye_key, b"webm-bytes" * 100),
    ):
        written = tmp_path / key
        written.parent.mkdir(parents=True, exist_ok=True)
        written.write_bytes(content)
        await desk.webhook(
            "egress_ended",
            egress={
                "egress_id": egress_id,
                "status": "complete",
                "filename": key,
                "size": len(content),
                "duration_ms": 61_000,
                "started_at": datetime.now(UTC).isoformat(),
            },
        )
    async with app_db.tenant(org) as session:
        queued = (
            await session.scalars(select(OutboxEvent).where(OutboxEvent.topic == egress.TOPIC))
        ).all()
    assert len(queued) == 2
    output = egress.SharedVolumeOutput(tmp_path, "/out", storage)
    for event in queued:
        await egress.collect(app_db, valkey, output, storage, org, event.payload)
    assert not (tmp_path / audio_key).exists()  # moved into blob storage

    async with app_db.tenant(org) as session:
        rows = (await session.scalars(select(Recording).order_by(Recording.track))).all()
    assert [(r.track, r.source, r.status) for r in rows] == [
        ("conversation-audio-1", "egress", "assembled"),
        ("third-eye-1", "egress", "assembled"),
    ]
    assert rows[0].assembled_bytes == len(b"audio-bytes" * 100) and rows[0].duration_ms == 61_000
    async with app_db.tenant(org) as session:
        listed = await playable_tracks(session, storage, org, UUID(interview))
    assert [(t.track, t.file is not None, t.timeline_url is not None) for t in listed] == [
        ("conversation-audio-1", True, True),
        ("third-eye-1", True, True),
    ]
    assert listed[1].file is not None and listed[1].file.container == "webm"
