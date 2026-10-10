"""The desktop's recording routes (SP-12): `docs/api/contracts/recordings.md` with a DPoP desktop,
real upload URLs against Azurite, hash-verified acknowledgement and the recovery listing."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_api.app import create_app
from hirevion_api.settings import ApiSettings
from hirevion_core.db.session import Database
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.models import OutboxEvent, Recording, RecordingSegment
from hirevion_core.recordings.assembly import Assembler
from hirevion_core.recordings.settings import RecordingSettings
from hirevion_core.storage.service import StorageService, ensure_storage, load_storage_settings
from hirevion_interview_simulator.client import DesktopClient
from hirevion_interview_simulator.seed import Seeded, seed_interview

pytestmark = pytest.mark.db

BASE = "http://api.hirevion.localhost"
ORIGIN = "https://app.hirevion.localhost"
IDENTITY = IdentitySettings(hibp_enabled=False, web_origin=ORIGIN)
PASSWORD = "a long simulated passphrase"  # noqa: S105 (a test password)
MakeOrganization = Callable[[str], Awaitable[UUID]]
DATA = b"ftypisom-segment-" * 1000


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
async def storage() -> AsyncIterator[StorageService]:
    settings = load_storage_settings()
    # Straight to Azurite: tests don't go through Caddy's TLS, which CI doesn't have.
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


@pytest.fixture
def client(api: FastAPI, client_for: Callable[[FastAPI], AsyncClient]) -> AsyncClient:
    return client_for(api)


class Desktop:
    """A desktop with an interview-session token for an interview that has started."""

    def __init__(self, desktop: DesktopClient, seed: Seeded, recruiter: UUID) -> None:
        self.client = desktop
        self.seed = seed
        self.recruiter = recruiter
        self.interview = str(seed.interview_id)

    def call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Awaitable[Any]:
        return self.client.call(
            method, path, json=body, token=self.client.session_tokens[self.interview]
        )

    def segment_body(self, **changes: Any) -> dict[str, Any]:
        body: dict[str, Any] = {
            "interview_id": self.interview,
            "track": "screen-1",
            "seq": 0,
            "started_at": "2026-10-12T05:03:20.000Z",
            "duration_ms": 10_000,
            "bytes": len(DATA),
            "sha256": sha(DATA),
            "container": "mp4",
            "codec": "h264",
        }
        return {**body, **changes}

    async def ask(self, **changes: Any) -> httpx.Response:
        return await self.call("POST", "/recordings/segments", self.segment_body(**changes))  # type: ignore[no-any-return]

    async def upload(self, grant: dict[str, Any], data: bytes = DATA) -> None:
        async with httpx.AsyncClient() as http:
            stored = await http.put(grant["upload_url"], content=data, headers=grant["headers"])
        assert stored.status_code == 201, stored.text

    async def ack(self, segment_id: str, digest: str | None = None) -> httpx.Response:
        return await self.call(  # type: ignore[no-any-return]
            "POST", f"/recordings/segments/{segment_id}/ack", {"sha256": digest or sha(DATA)}
        )

    async def send(self, **changes: Any) -> str:
        """Asks for a URL, uploads `DATA` and acknowledges it; returns the segment id."""
        asked = await self.ask(**changes)
        assert asked.status_code == 200, asked.text
        grant = asked.json()
        await self.upload(grant)
        done = await self.ack(grant["segment_id"], changes.get("sha256"))
        assert done.status_code == 200, done.text
        return str(grant["segment_id"])


async def started_desktop(
    client: AsyncClient,
    admin_engine: AsyncEngine,
    app_db: Database,
    make_organization: MakeOrganization,
    make_user: Any,
    *,
    status: str = "in_progress",
    policy_recording: dict[str, bool] | None = None,
) -> Desktop:
    org = await make_organization("Acme")
    recruiter = await make_user(org, roles=["recruiter"])
    seed = await seed_interview(
        admin_engine, app_db, org, recruiter, password=PASSWORD, settings=IDENTITY
    )
    desktop = DesktopClient(client, base_url=BASE)
    await desktop.login(seed.email, PASSWORD)
    await desktop.session_token(str(seed.interview_id))
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE interviews SET status = :status, started_at = :at WHERE id = :id"),
            {
                "status": status,
                "at": datetime.now(UTC) - timedelta(minutes=2) if status != "invited" else None,
                "id": seed.interview_id,
            },
        )
        if policy_recording is not None:
            await conn.execute(
                text(
                    "UPDATE interviews SET policy = jsonb_set(policy, '{recording}', "
                    "CAST(:recording AS jsonb)) WHERE id = :id"
                ),
                {"recording": json.dumps(policy_recording), "id": seed.interview_id},
            )
    return Desktop(desktop, seed, recruiter)


async def test_a_segment_goes_from_url_to_upload_to_acknowledgement(
    client: AsyncClient,
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user: Any,
    storage: StorageService,
) -> None:
    desktop = await started_desktop(client, admin_engine, app_db, make_organization, make_user)
    asked = await desktop.ask()
    assert asked.status_code == 200
    grant = asked.json()
    assert set(grant) == {"segment_id", "upload_url", "expires_at", "headers"}
    assert grant["headers"] == {"x-ms-blob-type": "BlockBlob", "Content-Type": "video/mp4"}
    expires = datetime.fromisoformat(grant["expires_at"])
    assert timedelta(minutes=14) < expires - datetime.now(UTC) <= timedelta(minutes=15)
    org, interview = desktop.seed.organization_id, desktop.seed.interview_id
    assert f"/{org}/interviews/{interview}/screen/" in grant["upload_url"]  # PRD §85's layout

    # The URL writes one blob and can't read it back.
    await desktop.upload(grant)
    async with httpx.AsyncClient() as http:
        assert (await http.get(grant["upload_url"])).status_code == 403

    done = await desktop.ack(grant["segment_id"])
    assert done.status_code == 200 and done.json() == {"status": "acknowledged"}
    async with app_db.tenant(org) as session:
        row = await session.get_one(RecordingSegment, UUID(grant["segment_id"]))
        recording = await session.scalar(
            select(Recording).where(Recording.interview_id == interview)
        )
    assert row.state == "acknowledged" and row.acknowledged_at is not None
    assert row.blob_path.startswith(f"{org}/interviews/{interview}/screen/screen-1-000000.mp4")
    assert await storage.exists(storage_path(row))
    assert recording is not None and (recording.track, recording.first_seq, recording.last_seq) == (
        "screen-1",
        0,
        0,
    )


def storage_path(row: RecordingSegment) -> Any:
    from hirevion_core.storage.paths import BlobPath

    return BlobPath(row.organization_id, row.blob_path.split("/", 1)[1])


async def test_asking_again_for_the_same_segment_gives_the_same_id_and_a_fresh_url(
    client: AsyncClient,
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user: Any,
) -> None:
    desktop = await started_desktop(client, admin_engine, app_db, make_organization, make_user)
    first = (await desktop.ask(seq=3)).json()
    second = (await desktop.ask(seq=3)).json()
    assert first["segment_id"] == second["segment_id"]
    assert second["upload_url"].split("?")[0] == first["upload_url"].split("?")[0]
    assert datetime.fromisoformat(second["expires_at"]) >= datetime.fromisoformat(
        first["expires_at"]
    )
    other = (await desktop.ask(seq=4)).json()
    assert other["segment_id"] != first["segment_id"]
    camera = (await desktop.ask(track="camera", container="webm", codec="vp8", seq=3)).json()
    assert camera["headers"]["Content-Type"] == "video/webm"
    assert "/camera/camera-000003.webm" in camera["upload_url"]
    mic = (await desktop.ask(track="mic", container="webm", codec="opus", seq=0)).json()
    assert mic["headers"]["Content-Type"] == "audio/webm"
    assert "/audio/mic-000000.webm" in mic["upload_url"]  # the mic goes in §85's audio folder


async def test_an_acknowledged_segment_is_done(
    client: AsyncClient,
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user: Any,
) -> None:
    desktop = await started_desktop(client, admin_engine, app_db, make_organization, make_user)
    segment_id = await desktop.send(seq=0)
    again = await desktop.ask(seq=0)
    assert again.status_code == 409 and again.json()["code"] == "segment-acknowledged"
    assert again.json()["segment_id"] == segment_id
    # Acknowledging twice is harmless, and with the wrong hash it is still refused.
    assert (await desktop.ack(segment_id)).json() == {"status": "acknowledged"}
    wrong = await desktop.ack(segment_id, sha(b"other"))
    assert wrong.status_code == 422 and wrong.json()["code"] == "hash-mismatch"


async def test_the_contracts_limits(
    client: AsyncClient,
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user: Any,
) -> None:
    desktop = await started_desktop(client, admin_engine, app_db, make_organization, make_user)
    exactly = await desktop.ask(seq=0, bytes=50_000_000, duration_ms=60_000)
    assert exactly.status_code == 200  # 50 MB is 50,000,000 bytes, and 60 s is allowed
    too_big = await desktop.ask(seq=1, bytes=50_000_001)
    assert too_big.status_code == 413 and too_big.json()["code"] == "segment-too-large"
    too_long = await desktop.ask(seq=2, duration_ms=60_001)
    assert too_long.status_code == 422 and too_long.json()["code"] == "segment-too-long"
    for changes, code in [
        ({"container": "webm", "codec": "vp8"}, "unsupported-format"),  # screens are mp4/h264
        ({"track": "camera", "container": "mp4", "codec": "vp8"}, "unsupported-format"),
        ({"track": "webcam"}, "validation-failed"),
        ({"track": "screen-9"}, "validation-failed"),
        ({"seq": -1}, "validation-failed"),
        ({"sha256": "not-a-hash"}, "validation-failed"),
        ({"bytes": 0}, "validation-failed"),
        ({"started_at": "2026-10-12T05:03:20"}, "validation-failed"),  # no time zone
    ]:
        refused = await desktop.ask(**changes)
        assert refused.status_code == 422 and refused.json()["code"] == code, (
            changes,
            refused.text,
        )


async def test_a_track_the_interview_does_not_record_is_refused(
    client: AsyncClient,
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user: Any,
) -> None:
    desktop = await started_desktop(
        client,
        admin_engine,
        app_db,
        make_organization,
        make_user,
        policy_recording={"screen": True, "camera": False, "audio": True},
    )
    refused = await desktop.ask(track="camera", container="webm", codec="vp8")
    assert refused.status_code == 422 and refused.json()["code"] == "track-not-recorded"
    assert (await desktop.ask(track="screen-2")).status_code == 200
    assert (await desktop.ask(track="mic", container="webm", codec="opus")).status_code == 200


async def test_only_the_token_s_own_interview_and_only_once_it_has_started(
    client: AsyncClient,
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user: Any,
) -> None:
    desktop = await started_desktop(client, admin_engine, app_db, make_organization, make_user)
    other = await desktop.ask(interview_id=str(uuid4()))
    assert other.status_code == 403 and other.json()["code"] == "wrong-interview"
    listing = await desktop.call("GET", f"/recordings/interviews/{uuid4()}/segments")
    assert listing.status_code == 403 and listing.json()["code"] == "wrong-interview"
    no_token = await desktop.client.http.post(
        f"{BASE}/api/v1/recordings/segments", json=desktop.segment_body()
    )
    assert no_token.status_code == 401
    no_proof = await desktop.client.http.post(
        f"{BASE}/api/v1/recordings/segments",
        json=desktop.segment_body(),
        headers={"Authorization": f"DPoP {desktop.client.session_tokens[desktop.interview]}"},
    )
    assert no_proof.status_code == 401 and no_proof.json()["code"] == "dpop-invalid"


async def test_nothing_is_taken_before_the_interview_starts(
    client: AsyncClient,
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user: Any,
) -> None:
    desktop = await started_desktop(
        client, admin_engine, app_db, make_organization, make_user, status="invited"
    )
    refused = await desktop.ask()
    assert refused.status_code == 409 and refused.json()["code"] == "interview-not-started"


async def test_uploads_are_still_taken_after_the_interview_ends(
    client: AsyncClient,
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user: Any,
) -> None:
    desktop = await started_desktop(
        client, admin_engine, app_db, make_organization, make_user, status="completed"
    )
    await desktop.send(seq=0)  # the desktop drains its queue after completing


async def test_a_corrupt_upload_is_refused_and_can_be_sent_again(
    client: AsyncClient,
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user: Any,
) -> None:
    desktop = await started_desktop(client, admin_engine, app_db, make_organization, make_user)
    grant = (await desktop.ask(seq=0)).json()
    await desktop.upload(grant, b"truncated")
    bad = await desktop.ack(grant["segment_id"])
    assert bad.status_code == 422 and bad.json()["code"] == "hash-mismatch"
    async with app_db.tenant(desktop.seed.organization_id) as session:
        row = await session.get_one(RecordingSegment, UUID(grant["segment_id"]))
    assert (row.state, row.attempts) == ("uploaded", 1)  # in storage, but not verified
    # A same-sized blob with other bytes fails the hash, not just the size.
    await desktop.upload(grant, b"x" * len(DATA))
    assert (await desktop.ack(grant["segment_id"])).json()["code"] == "hash-mismatch"
    # A URL can't cap the size it writes, so a blob far over the declared size is refused
    # without being read.
    await desktop.upload(grant, b"y" * (len(DATA) * 4))
    assert (await desktop.ack(grant["segment_id"])).json()["code"] == "hash-mismatch"

    retry = (await desktop.ask(seq=0)).json()
    assert retry["segment_id"] == grant["segment_id"]
    await desktop.upload(retry)
    assert (await desktop.ack(grant["segment_id"])).status_code == 200


async def test_a_missing_blob_and_a_stranger_s_segment(
    client: AsyncClient,
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user: Any,
) -> None:
    desktop = await started_desktop(client, admin_engine, app_db, make_organization, make_user)
    grant = (await desktop.ask(seq=0)).json()
    missing = await desktop.ack(grant["segment_id"])
    assert missing.status_code == 404 and missing.json()["code"] == "blob-missing"
    unknown = await desktop.ack(str(uuid4()))
    assert unknown.status_code == 404 and unknown.json()["code"] == "segment-not-found"
    # Another candidate's token can't reach this segment, and can't tell that it exists.
    stranger = await started_desktop(client, admin_engine, app_db, make_organization, make_user)
    refused = await stranger.ack(grant["segment_id"])
    assert refused.status_code == 404 and refused.json()["code"] == "segment-not-found"


async def test_recovery_lists_what_is_acknowledged_and_what_is_missing(
    client: AsyncClient,
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user: Any,
) -> None:
    desktop = await started_desktop(client, admin_engine, app_db, make_organization, make_user)
    path = f"/recordings/interviews/{desktop.interview}/segments"
    empty = (await desktop.call("GET", path)).json()
    assert empty == {
        "tracks": {
            "screen-1": {"acknowledged_through": None, "missing": []},
            "camera": {"acknowledged_through": None, "missing": []},
            "mic": {"acknowledged_through": None, "missing": []},
        }
    }
    for seq in (0, 1, 2, 4, 5):
        await desktop.send(seq=seq)
    (await desktop.ask(seq=3)).json()  # asked for, never uploaded
    (await desktop.ask(seq=6)).json()
    await desktop.send(track="camera", container="webm", codec="vp8", seq=0)
    tracks = (await desktop.call("GET", path)).json()["tracks"]
    assert tracks["screen-1"] == {"acknowledged_through": 5, "missing": [3]}
    assert tracks["camera"] == {"acknowledged_through": 0, "missing": []}
    assert tracks["mic"] == {"acknowledged_through": None, "missing": []}


async def test_a_later_seq_is_never_refused_and_skipped_numbers_are_gaps(
    client: AsyncClient,
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user: Any,
) -> None:
    desktop = await started_desktop(client, admin_engine, app_db, make_organization, make_user)
    await desktop.send(seq=0)
    await desktop.send(seq=1)
    await desktop.send(seq=5)  # a pause, or the MediaRecorder fallback after an early stop
    await desktop.send(seq=6)
    tracks = (
        await desktop.call("GET", f"/recordings/interviews/{desktop.interview}/segments")
    ).json()["tracks"]
    assert tracks["screen-1"] == {"acknowledged_through": 6, "missing": [2, 3, 4]}

    async with app_db.tenant(desktop.seed.organization_id) as session:
        events = (
            await session.scalars(select(OutboxEvent).where(OutboxEvent.topic == "recording.gap"))
        ).all()
        recording = await session.scalar(select(Recording).where(Recording.track == "screen-1"))
    (gap,) = [e.payload for e in events if e.payload["interview_id"] == desktop.interview]
    assert (gap["track"], gap["kind"], gap["state"]) == ("screen-1", "skipped", "closed")
    assert (gap["from_seq"], gap["to_seq"]) == (2, 4)
    assert gap["from_time"] and gap["to_time"]
    assert recording is not None and recording.last_seq == 6 and recording.first_seq == 0


async def test_the_first_segment_may_start_above_zero(
    client: AsyncClient,
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user: Any,
) -> None:
    desktop = await started_desktop(client, admin_engine, app_db, make_organization, make_user)
    await desktop.send(seq=3)
    tracks = (
        await desktop.call("GET", f"/recordings/interviews/{desktop.interview}/segments")
    ).json()["tracks"]
    assert tracks["screen-1"] == {"acknowledged_through": 3, "missing": [0, 1, 2]}


class JoinFfmpeg:
    """Joins files byte for byte, the way ffmpeg's `-c copy` joins whole segments."""

    path = "join"

    def available(self) -> bool:
        return True

    async def concat(
        self, workdir: Path, names: Sequence[str], output: str, container: str
    ) -> None:
        (workdir / output).write_bytes(b"".join((workdir / n).read_bytes() for n in names))


async def test_a_recording_goes_from_the_desktop_to_a_reviewer_s_playback(
    client: AsyncClient,
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user: Any,
    storage: StorageService,
    signed_in: Any,
) -> None:
    """The part's main path: segments uploaded and acknowledged during the interview, the
    interview completes, the media worker assembles the tracks, a reviewer plays them back."""
    desktop = await started_desktop(client, admin_engine, app_db, make_organization, make_user)
    org, interview = desktop.seed.organization_id, desktop.seed.interview_id
    for seq in (0, 1, 3):  # segment 2 never reaches the server
        await desktop.send(seq=seq)
    await desktop.send(track="mic", container="webm", codec="opus", seq=0)

    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE interviews SET status = 'completed' WHERE id = :id"), {"id": interview}
        )
    worker = Assembler(app_db, storage, JoinFfmpeg(), RecordingSettings())
    assert await worker.assemble_interview(org, interview) == 2

    browser = await signed_in(org, desktop.recruiter)
    body = (await browser.get(f"/api/v1/interviews/{interview}/recordings")).json()
    screen, mic = body["tracks"][0], body["tracks"][1]
    assert (screen["track"], screen["status"], mic["track"]) == ("screen-1", "assembled", "mic")
    assert screen["file"]["duration_ms"] == 30_000 and screen["segments"] == []
    assert [(g["from_seq"], g["to_seq"]) for g in screen["gaps"]] == [(2, 2)]
    async with httpx.AsyncClient() as http:
        assert (await http.get(screen["file"]["url"])).content == DATA * 3
        timeline = (await http.get(screen["timeline_url"])).json()
    assert [s["seq"] for s in timeline["segments"]] == [0, 1, 3]
    assert [s["file_offset_ms"] for s in timeline["segments"]] == [0, 10_000, 20_000]

    # The recovery listing still says what the desktop needs to know.
    tracks = (
        await desktop.call("GET", f"/recordings/interviews/{desktop.interview}/segments")
    ).json()["tracks"]
    assert tracks["screen-1"] == {"acknowledged_through": 3, "missing": [2]}
