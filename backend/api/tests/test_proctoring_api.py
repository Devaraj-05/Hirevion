"""Proctoring over HTTP (SP-14): `proctoring.md` with a DPoP desktop, the recruiter's report,
live snapshot, evidence and reviews, the live websocket, and LiveKit's track events.

Exit criteria: events reach the dashboard in under 1 s (p95), a reconnecting dashboard receives
the alerts it missed, and dismissed events are audited and still reported."""

from __future__ import annotations

import asyncio
import base64
import json
import statistics
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_api.app import create_app
from hirevion_api.auth.cookies import SESSION_COOKIE
from hirevion_api.settings import ApiSettings
from hirevion_core.ai import build_ai
from hirevion_core.ai.settings import AiSettings
from hirevion_core.db.session import Database
from hirevion_core.identity.sessions import create_session
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.interview_session.media import FakeMedia
from hirevion_core.models import AuditLog, ProctorEvent
from hirevion_core.proctoring.service import ProctorEngine
from hirevion_core.storage.service import StorageService, StorageSettings
from hirevion_interview_simulator.client import DesktopClient
from hirevion_interview_simulator.seed import Seeded, seed_interview

pytestmark = pytest.mark.db

BASE = "http://api.hirevion.localhost"
ORIGIN = "https://app.hirevion.localhost"
IDENTITY = IdentitySettings(hibp_enabled=False, web_origin=ORIGIN)
PASSWORD = "a long simulated passphrase"  # noqa: S105 (a test password)
MakeOrganization = Callable[[str], Awaitable[UUID]]
STORAGE = StorageService(
    StorageSettings(
        azure_storage_account="hirevion", azure_storage_key=base64.b64encode(b"k" * 64).decode()
    )  # type: ignore[arg-type]
)


@pytest.fixture
def media() -> FakeMedia:
    return FakeMedia()


@pytest.fixture
def api(app_db: Database, valkey: Redis, media: FakeMedia) -> FastAPI:
    return create_app(
        ApiSettings(allowed_origins=ORIGIN, run_workers=False, ip_rate_limit=100_000),
        db=app_db,
        redis=valkey,
        identity=IDENTITY,
        ai=build_ai(AiSettings(profile="mock"), app_db),
        media=media,
        storage=STORAGE,
    )


@pytest.fixture
def client(api: FastAPI, client_for: Callable[[FastAPI], AsyncClient]) -> AsyncClient:
    return client_for(api)


def now() -> datetime:
    return datetime.now(UTC)


class Desk:
    """A started interview with its desktop, its recruiter and an open proctor session."""

    def __init__(self, seed: Seeded, recruiter: UUID, desktop: DesktopClient) -> None:
        self.seed, self.recruiter, self.desktop = seed, recruiter, desktop
        self.interview = str(seed.interview_id)
        self.token = ""
        self.session_id = ""

    def call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        return self.desktop.call(method, path, json=body, token=self.token)

    async def events(self, *events: dict[str, Any]) -> Any:
        return await self.call(
            "POST",
            "/proctoring/events",
            {"proctor_session_id": self.session_id, "events": list(events)},
        )

    async def heartbeat(self, **changes: Any) -> Any:
        body = {
            "proctor_session_id": self.session_id,
            "seq_high": 0,
            "camera": "on",
            "mic": "on",
            "screen": "capturing",
            "third_eye": "not_required",
            "displays": 1,
            **changes,
        }
        return await self.call("POST", "/proctoring/heartbeat", body)


def event(seq: int, name: str = "WINDOW_MINIMIZED", **fields: Any) -> dict[str, Any]:
    return {
        "seq": seq,
        "event": name,
        "source": fields.pop("source", "native"),
        "started_at": now().isoformat(),
        **fields,
    }


@pytest.fixture
async def desk(
    client: AsyncClient,
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user: Any,
) -> Desk:
    org = await make_organization("Acme")
    recruiter = await make_user(org, roles=["recruiter"])
    seed = await seed_interview(
        admin_engine, app_db, org, recruiter, password=PASSWORD, settings=IDENTITY
    )
    desktop = DesktopClient(client, base_url=BASE)
    await desktop.login(seed.email, PASSWORD)
    interview = str(seed.interview_id)
    await desktop.session_token(interview)
    briefing = await desktop.briefing(interview)
    check = await desktop.system_check(interview, briefing["mandatory_checks"])
    consent = await desktop.consent(interview, briefing["notice"])
    await desktop.start(interview, check["id"], consent["id"])
    made = Desk(seed, recruiter, desktop)
    made.token = desktop.session_tokens[interview]
    opened = await made.call(
        "POST", "/proctoring/session", {"interview_id": interview, "app_version": "1.4.0"}
    )
    assert opened.status_code == 200, opened.text
    made.session_id = opened.json()["proctor_session_id"]
    return made


async def cookie(app_db: Database, org: UUID, user: UUID) -> str:
    async with app_db.tenant(org) as session:
        token, _, _ = await create_session(
            session,
            user_id=user,
            organization_id=org,
            ip=None,
            user_agent=None,
            settings=IDENTITY,
            now=now(),
        )
    return f"{SESSION_COOKIE}={token}"


# The desktop's contract.


async def test_the_session_answer_follows_the_contract(desk: Desk) -> None:
    again = await desk.call(
        "POST", "/proctoring/session", {"interview_id": desk.interview, "app_version": "1.4.1"}
    )
    body = again.json()
    assert body["proctor_session_id"] == desk.session_id
    assert body["level"] == "standard" and body["policy_version"] == 1
    assert body["checks"] == ["face", "focus", "gaze", "phone", "processes", "displays"]
    assert body["thresholds"]["FACE_ABSENT"] == {"warn_after_ms": 5000, "critical_after_ms": 30000}
    assert body["heartbeat_seconds"] == 5 and body["batch_max_events"] == 100
    assert body["single_display"] is False and body["accommodations"] == ["text_answers"]
    assert body["acked_through"] == 0
    blocked = body["app_rules"]["blocked"]
    teamviewer = next(rule for rule in blocked if rule["value"] == "TeamViewer Germany GmbH")
    assert teamviewer["match"] == "publisher" and teamviewer["category"] == "remote_access"
    teams = next(rule for rule in blocked if rule["value"] == "ms-teams")
    assert teams["match"] == "name" and teams["with"] == [
        {"match": "publisher", "value": "Microsoft Corporation"}
    ]
    other = await desk.call(
        "POST", "/proctoring/session", {"interview_id": str(UUID(int=7)), "app_version": "1"}
    )
    assert other.status_code == 403 and other.json()["code"] == "wrong-interview"
    unproved = await desk.desktop.http.post(
        f"{BASE}/api/v1/proctoring/events", json={}, headers={"Authorization": f"DPoP {desk.token}"}
    )
    assert unproved.status_code == 401 and unproved.json()["code"] == "dpop-invalid"


async def test_events_are_idempotent_and_report_what_is_missing(desk: Desk) -> None:
    first = await desk.events(event(1), event(2, "PHONE_DETECTED", source="camera"))
    assert first.status_code == 200 and first.json() == {"acked_through": 2, "missing": []}
    skipped = await desk.events(event(5))
    assert skipped.json() == {"acked_through": 2, "missing": [3, 4]}
    retry = await desk.events(event(1), event(2, "PHONE_DETECTED", source="camera"), event(5))
    assert retry.json() == {"acked_through": 2, "missing": [3, 4]}
    filled = await desk.events(event(3), event(4))
    assert filled.json() == {"acked_through": 5, "missing": []}
    reopened = await desk.call(
        "POST", "/proctoring/session", {"interview_id": desk.interview, "app_version": "1.4.0"}
    )
    assert reopened.json()["acked_through"] == 5  # a client that lost its queue continues here


async def test_a_batch_with_an_unknown_event_or_too_many_events_is_refused(desk: Desk) -> None:
    unknown = await desk.events(event(1), event(2, "MAKE_COFFEE"))
    assert unknown.status_code == 422 and unknown.json()["code"] == "unknown-event"
    bad_source = await desk.events(event(1, source="satellite"))
    assert bad_source.json()["code"] == "unknown-event"
    server_only = await desk.events(event(1, "TELEMETRY_GAP"))
    assert server_only.json()["code"] == "unknown-event"
    many = await desk.events(*(event(n) for n in range(1, 102)))
    assert many.status_code == 422 and many.json()["code"] == "batch-too-large"
    assert (await desk.events(event(1))).json() == {"acked_through": 1, "missing": []}


async def test_heartbeats_answer_with_the_server_time_and_what_has_not_arrived(desk: Desk) -> None:
    answer = await desk.heartbeat(seq_high=3)
    assert answer.status_code == 200
    body = answer.json()
    assert body["missing"] == [1, 2, 3] and datetime.fromisoformat(body["server_time"])
    await desk.events(event(1), event(2), event(3))
    assert (await desk.heartbeat(seq_high=3)).json()["missing"] == []


async def test_after_the_interview_events_drain_but_heartbeats_are_refused(desk: Desk) -> None:
    await desk.desktop.complete(desk.interview, "candidate_ended")
    drained = await desk.events(event(1, "PHONE_DETECTED", source="camera"))
    assert drained.status_code == 200
    late = await desk.heartbeat()
    assert late.status_code == 409 and late.json()["code"] == "proctor-session-closed"


async def test_evidence_uploads_are_write_only_urls_for_one_blob(desk: Desk) -> None:
    body = {
        "proctor_session_id": desk.session_id,
        "kind": "screen",
        "seq": 41,
        "content_type": "image/jpeg",
        "bytes": 84_213,
        "sha256": "c" * 64,
    }
    answer = await desk.call("POST", "/proctoring/evidence-uploads", body)
    assert answer.status_code == 200, answer.text
    slot = answer.json()
    assert slot["blob_path"].endswith("/evidence/41-screen.jpg")
    assert slot["headers"] == {"x-ms-blob-type": "BlockBlob"}
    assert "sp=cw" in slot["upload_url"] and "se=" in slot["upload_url"]
    refused = await desk.call(
        "POST", "/proctoring/evidence-uploads", {**body, "content_type": "text/html"}
    )
    assert refused.status_code == 422
    linked = await desk.events(
        event(
            41,
            "BLOCKED_PROCESS_DETECTED",
            evidence=[{"type": "snapshot", "blob_path": slot["blob_path"]}],
            details={"name": "anydesk.exe", "category": "remote_access"},
        )
    )
    assert linked.status_code == 200


# The recruiter.


async def test_the_report_keeps_dismissed_events_and_the_review_is_audited(
    desk: Desk, client: AsyncClient, app_db: Database, signed_in: Any
) -> None:
    await desk.events(
        event(1, "PHONE_DETECTED", source="camera"),
        event(2, "FACE_ABSENT", source="camera", duration_ms=6000),
        event(3, "VM_DETECTED"),
    )
    browser = await signed_in(desk.seed.organization_id, desk.recruiter)
    report = (await browser.get(f"/api/v1/proctoring/{desk.interview}")).json()
    assert {e["event"] for e in report["events"]} == {
        "PHONE_DETECTED",
        "FACE_ABSENT",
        "VM_DETECTED",
    }
    assert report["counts"]["by_severity"] == {"INFO": 1, "WARNING": 1, "CRITICAL": 1}
    assert report["session"]["status"] == "open" and report["status"]["session"] == "open"
    phone = next(e for e in report["events"] if e["event"] == "PHONE_DETECTED")
    assert (
        phone["severity"] == "CRITICAL"
        and phone["review_status"] == "pending"
        and phone["review"] is None
    )

    path = f"/api/v1/proctoring/{desk.interview}/events/{phone['id']}/review"
    empty = await browser.post(path, json={"outcome": "false_positive", "reason": "  "})
    assert empty.status_code in (400, 422)
    dismissed = await browser.post(
        path, json={"outcome": "false_positive", "reason": "A poster on the wall"}
    )
    assert dismissed.status_code == 200, dismissed.text
    assert dismissed.json()["review_status"] == "false_positive"
    assert dismissed.json()["review"]["reason"] == "A poster on the wall"

    after = (await browser.get(f"/api/v1/proctoring/{desk.interview}")).json()
    assert len(after["events"]) == 3  # still in the report
    assert after["counts"]["dismissed"] == 1 and after["counts"]["open_alerts"] == 1
    kept = next(e for e in after["events"] if e["id"] == phone["id"])
    assert (
        kept["review_status"] == "false_positive" and kept["review"]["outcome"] == "false_positive"
    )
    filtered = (
        await browser.get(f"/api/v1/proctoring/{desk.interview}?review_status=false_positive")
    ).json()
    assert [e["id"] for e in filtered["events"]] == [phone["id"]]

    async with app_db.tenant(desk.seed.organization_id) as session:
        entries = (
            await session.scalars(
                select(AuditLog).where(AuditLog.action == "proctoring.event_reviewed")
            )
        ).all()
    assert len(entries) == 1
    assert (
        entries[0].details["outcome"] == "false_positive"
        and entries[0].details["previous"] == "pending"
    )
    assert entries[0].details["event"] == "PHONE_DETECTED"


async def test_only_those_who_may_see_proctoring_do(
    desk: Desk,
    app_db: Database,
    make_organization: MakeOrganization,
    make_user: Any,
    signed_in: Any,
) -> None:
    await desk.events(event(1, "PHONE_DETECTED", source="camera"))
    org = desk.seed.organization_id
    interviewer = await make_user(org, roles=["interviewer"])
    manager = await make_user(org, roles=["hiring_manager"])
    globex = await make_organization("Globex")
    stranger = await make_user(globex, roles=["recruiter"])
    path = f"/api/v1/proctoring/{desk.interview}"
    assert (await (await signed_in(org, interviewer)).get(path)).status_code == 403
    assert (await (await signed_in(org, manager)).get(path)).status_code == 200
    outsider = await signed_in(globex, stranger)
    assert (await outsider.get(path)).status_code in (403, 404)
    # Looking is one thing, deciding another.
    manager_client = await signed_in(org, manager)
    events = (await manager_client.get(path)).json()["events"]
    review = await manager_client.post(
        f"{path}/events/{events[0]['id']}/review", json={"outcome": "confirmed", "reason": "Seen"}
    )
    assert review.status_code == 403


async def test_the_live_snapshot_and_the_observer_token_are_audited(
    desk: Desk, app_db: Database, media: FakeMedia, signed_in: Any
) -> None:
    await desk.events(event(1, "PHONE_DETECTED", source="camera"))
    await desk.heartbeat(camera="off")
    browser = await signed_in(desk.seed.organization_id, desk.recruiter)
    snapshot = (await browser.get(f"/api/v1/proctoring/{desk.interview}/live")).json()
    assert snapshot["interview"]["status"] == "in_progress"
    assert snapshot["proctoring"]["connection"]["state"] == "ok"
    assert snapshot["proctoring"]["devices"]["screen"] == "up"
    assert snapshot["counts"]["by_severity"]["CRITICAL"] == 1
    assert [e["event"] for e in snapshot["events"]] == ["PHONE_DETECTED"]
    assert snapshot["cursor"] != "0-0" and snapshot["ai"]["agent_connected"] is False
    observe = await browser.post(f"/api/v1/proctoring/{desk.interview}/observe")
    assert observe.status_code == 200, observe.text
    token = observe.json()
    assert token["identity"].startswith("observer-") and token["room"] == f"iv-{desk.interview}"
    assert media.tokens[-1].identity == token["identity"]
    await browser.get(f"/api/v1/proctoring/{desk.interview}/live")  # inside the quiet period
    async with app_db.tenant(desk.seed.organization_id) as session:
        actions = [
            e.action for e in (await session.scalars(select(AuditLog).order_by(AuditLog.seq))).all()
        ]
    assert actions.count("proctoring.live_viewed") == 1
    assert actions.count("proctoring.observed") == 1


async def test_evidence_is_listed_with_links_and_viewing_it_is_audited(
    desk: Desk, app_db: Database, signed_in: Any
) -> None:
    slot = (
        await desk.call(
            "POST",
            "/proctoring/evidence-uploads",
            {
                "proctor_session_id": desk.session_id,
                "kind": "screen",
                "seq": 1,
                "content_type": "image/png",
                "bytes": 1000,
                "sha256": "d" * 64,
            },
        )
    ).json()
    await desk.events(
        event(
            1,
            "BLOCKED_PROCESS_DETECTED",
            evidence=[{"type": "snapshot", "blob_path": slot["blob_path"]}],
            details={
                "name": "anydesk.exe",
                "publisher": "philandro Software GmbH",
                "category": "remote_access",
            },
        )
    )
    browser = await signed_in(desk.seed.organization_id, desk.recruiter)
    items = (await browser.get(f"/api/v1/proctoring/{desk.interview}/evidence")).json()["items"]
    kinds = {item["kind"] for item in items}
    assert {"screenshot", "process_metadata"} <= kinds
    shot = next(item for item in items if item["kind"] == "screenshot")
    assert shot["url"] and "sp=r" in shot["url"] and shot["sha256"] == "d" * 64
    metadata = next(item for item in items if item["kind"] == "process_metadata")
    assert metadata["ref"]["name"] == "anydesk.exe" and metadata["url"] is None
    async with app_db.tenant(desk.seed.organization_id) as session:
        viewed = (
            await session.scalars(
                select(AuditLog).where(AuditLog.action == "proctoring.evidence_viewed")
            )
        ).all()
    assert len(viewed) == 1 and viewed[0].details["items"] == len(items)


# LiveKit's view.


async def test_livekits_track_events_become_server_observed_events(
    desk: Desk, client: AsyncClient, app_db: Database, valkey: Redis
) -> None:
    def webhook(kind: str, **fields: Any) -> dict[str, Any]:
        return {
            "content": json.dumps(
                {
                    "kind": kind,
                    "interview_id": desk.interview,
                    "organization_id": str(desk.seed.organization_id),
                    "identity": "candidate-x",
                    **fields,
                }
            ),
            "headers": {"Authorization": "fake-signature"},
        }

    earlier = (now() - timedelta(seconds=30)).isoformat()
    sent = await client.post(
        "/api/v1/livekit/webhook", **webhook("track_unpublished", track="camera", at=earlier)
    )
    assert sent.status_code == 204
    # The desktop still says the camera is on: LiveKit's view stands.
    await desk.heartbeat(camera="on")
    await ProctorEngine(app_db, valkey).tick(desk.seed.organization_id, UUID(desk.session_id))
    async with app_db.tenant(desk.seed.organization_id) as session:
        rows = (await session.scalars(select(ProctorEvent))).all()
    assert [(r.event, r.severity, r.origin) for r in rows] == [
        ("CAMERA_DISCONNECTED", "CRITICAL", "server")
    ]
    assert rows[0].details["sources"] == ["livekit"]
    back = await client.post(
        "/api/v1/livekit/webhook", **webhook("track_published", track="camera")
    )
    assert back.status_code == 204


# The exit criteria.


class Live:
    """A recruiter's websocket on the app, open in this event loop, with the time each message
    arrived."""

    def __init__(self, app: FastAPI, path: str, headers: dict[str, str]) -> None:
        self.app, self.path, self.headers = app, path, headers
        self.messages: list[tuple[float, dict[str, Any]]] = []
        self.closed: list[int] = []
        self._inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._changed = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> Live:
        await self._inbox.put({"type": "websocket.connect"})
        route, _, query = self.path.partition("?")
        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0"},
            "scheme": "ws",
            "path": route,
            "raw_path": route.encode(),
            "query_string": query.encode(),
            "root_path": "",
            "headers": [(k.lower().encode(), v.encode()) for k, v in self.headers.items()]
            + [(b"host", b"api.hirevion.localhost")],
            "client": ("127.0.0.1", 50000),
            "server": ("api.hirevion.localhost", 80),
            "subprotocols": [],
            "state": {},
        }

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "websocket.send":
                self.messages.append((time.perf_counter(), json.loads(message["text"])))
            elif message["type"] == "websocket.close":
                self.closed.append(int(message.get("code", 1000)))
            self._changed.set()

        self._task = asyncio.create_task(self.app(scope, self._inbox.get, send))  # type: ignore[arg-type]
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._inbox.put({"type": "websocket.disconnect", "code": 1000})
        assert self._task is not None
        try:
            await asyncio.wait_for(self._task, 5)
        except TimeoutError:
            self._task.cancel()

    def alerts(self) -> list[dict[str, Any]]:
        return [m for _, m in self.messages if m.get("type") == "PROCTOR_EVENT"]

    async def until(self, ready: Callable[[], bool], seconds: float = 5) -> None:
        deadline = time.perf_counter() + seconds
        while not ready():
            if self.closed:
                return
            left = deadline - time.perf_counter()
            if left <= 0:
                raise TimeoutError(
                    f"the live view got {self.messages!r} and closed {self.closed!r}"
                )
            self._changed.clear()
            if ready():
                return
            try:
                await asyncio.wait_for(self._changed.wait(), left)
            except TimeoutError:
                continue


async def test_the_live_view_needs_the_right_origin_session_and_permissions(
    api: FastAPI, desk: Desk, app_db: Database, make_user: Any
) -> None:
    path = f"/api/v1/ws/proctoring/{desk.interview}"
    org = desk.seed.organization_id
    good = await cookie(app_db, org, desk.recruiter)
    async with Live(api, path, {"origin": "https://evil.example", "cookie": good}) as evil:
        await evil.until(lambda: bool(evil.closed))
    assert evil.closed == [1008]
    async with Live(api, path, {"origin": ORIGIN}) as anonymous:
        await anonymous.until(lambda: bool(anonymous.closed))
    assert anonymous.closed == [4401]
    interviewer = await make_user(org, roles=["interviewer"])
    async with Live(
        api, path, {"origin": ORIGIN, "cookie": await cookie(app_db, org, interviewer)}
    ) as nope:
        await nope.until(lambda: bool(nope.closed))
    assert nope.closed == [4403]


async def test_the_interview_stream_hides_proctoring_from_those_who_may_not_see_it(
    api: FastAPI, desk: Desk, app_db: Database, make_user: Any
) -> None:
    org = desk.seed.organization_id
    reviewer = await make_user(org, roles=["interviewer"])
    async with app_db.tenant(org) as session:
        await session.execute(
            text(
                "INSERT INTO interview_reviewers (organization_id, interview_id, user_id) "
                "VALUES (:org, :iv, :user)"
            ),
            {"org": org, "iv": desk.seed.interview_id, "user": reviewer},
        )
    await desk.events(event(1, "PHONE_DETECTED", source="camera"))
    headers = {"origin": ORIGIN, "cookie": await cookie(app_db, org, reviewer)}
    async with Live(api, f"/api/v1/ws/interviews/{desk.interview}", headers) as interviewer_view:
        await interviewer_view.until(lambda: bool(interviewer_view.messages))
    assert interviewer_view.closed == []
    assert not any(m.get("type", "").startswith("PROCTOR") for _, m in interviewer_view.messages)
    boss = {"origin": ORIGIN, "cookie": await cookie(app_db, org, desk.recruiter)}
    async with Live(api, f"/api/v1/ws/interviews/{desk.interview}", boss) as recruiter_view:
        await recruiter_view.until(lambda: bool(recruiter_view.alerts()))
    assert recruiter_view.alerts()[0]["data"]["event"] == "PHONE_DETECTED"


async def test_a_reconnecting_dashboard_receives_the_alerts_it_missed(
    api: FastAPI, desk: Desk, app_db: Database
) -> None:
    headers = {
        "origin": ORIGIN,
        "cookie": await cookie(app_db, desk.seed.organization_id, desk.recruiter),
    }
    path = f"/api/v1/ws/proctoring/{desk.interview}"
    await desk.events(event(1, "PHONE_DETECTED", source="camera"))
    async with Live(api, path, headers) as first:
        await first.until(lambda: len(first.alerts()) >= 1)
    last = first.alerts()[-1]["id"]
    assert [a["data"]["seq"] for a in first.alerts()] == [1]

    # The dashboard is gone while three more alerts happen.
    for seq in (2, 3, 4):
        await desk.events(event(seq, "MULTIPLE_FACES", source="camera", duration_ms=4000))
    async with Live(api, f"{path}?after={last}", headers) as second:
        await second.until(lambda: len(second.alerts()) >= 3)
    assert [a["data"]["seq"] for a in second.alerts()] == [2, 3, 4]
    assert all(a["data"]["severity"] == "CRITICAL" for a in second.alerts())


async def test_events_reach_the_dashboard_in_under_a_second_at_the_95th_percentile(
    api: FastAPI, desk: Desk, app_db: Database
) -> None:
    headers = {
        "origin": ORIGIN,
        "cookie": await cookie(app_db, desk.seed.organization_id, desk.recruiter),
    }
    path = f"/api/v1/ws/proctoring/{desk.interview}?after=0"
    latencies: list[float] = []
    async with Live(api, path, headers) as live:
        await live.until(lambda: bool(live.messages))  # the session's status: the socket is open
        for seq in range(1, 41):
            sent = time.perf_counter()
            answer = await desk.events(event(seq, "WINDOW_MINIMIZED", duration_ms=4000))
            assert answer.status_code == 200
            await live.until(lambda s=seq: any(a["data"]["seq"] == s for a in live.alerts()))
            arrived = next(
                t
                for t, m in live.messages
                if m.get("type") == "PROCTOR_EVENT" and m["data"]["seq"] == seq
            )
            latencies.append(arrived - sent)
    ordered = sorted(latencies)
    p95 = ordered[int(len(ordered) * 0.95) - 1]
    print(
        f"proctoring latency (POST /proctoring/events to the dashboard, {len(ordered)} events): "
        f"median {statistics.median(ordered) * 1000:.0f} ms, p95 {p95 * 1000:.0f} ms, "
        f"max {ordered[-1] * 1000:.0f} ms"
    )
    assert p95 < 1.0
