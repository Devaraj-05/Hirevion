"""The interview session over HTTP (SP-09 Tasks 4 and 6): `interview-session.md` with a DPoP
desktop, every simulator persona through a full interview on the mock AI, the recruiter's
transcript, accommodations and briefing, LiveKit's webhook, and the live events websocket.

Exit criteria: every persona finishes a full interview, and required skills are covered.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_api.app import create_app
from hirevion_api.auth.cookies import CSRF_COOKIE, SESSION_COOKIE
from hirevion_api.settings import ApiSettings
from hirevion_core.ai import build_ai
from hirevion_core.ai.settings import AiSettings
from hirevion_core.db.session import Database
from hirevion_core.identity.sessions import create_session
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.interview_session.media import FakeMedia
from hirevion_core.models import Interview, InterviewAnswer
from hirevion_interview_simulator.client import DesktopClient
from hirevion_interview_simulator.personas import PERSONAS, persona
from hirevion_interview_simulator.run import simulate
from hirevion_interview_simulator.seed import Seeded, seed_interview

pytestmark = pytest.mark.db

BASE = "http://api.hirevion.localhost"
ORIGIN = "https://app.hirevion.localhost"
IDENTITY = IdentitySettings(hibp_enabled=False, web_origin=ORIGIN)
PASSWORD = "a long simulated passphrase"  # noqa: S105 (a test password)
MakeOrganization = Callable[[str], Awaitable[UUID]]


@pytest.fixture
def media() -> FakeMedia:
    return FakeMedia()


@pytest.fixture
def api(app_db: Database, valkey: Redis, media: FakeMedia) -> FastAPI:
    """The API with fake media and the mock AI (the conftest's `api`, overridden)."""
    return create_app(
        ApiSettings(allowed_origins=ORIGIN, run_workers=False, ip_rate_limit=100_000),
        db=app_db,
        redis=valkey,
        identity=IDENTITY,
        ai=build_ai(AiSettings(profile="mock"), app_db),
        media=media,
    )


@pytest.fixture
def client(api: FastAPI, client_for: Callable[[FastAPI], AsyncClient]) -> AsyncClient:
    return client_for(api)


async def seeded(
    admin_engine: AsyncEngine,
    app_db: Database,
    make_organization: MakeOrganization,
    make_user: Any,
    *,
    text_answers: bool = True,
) -> tuple[Seeded, UUID]:
    org = await make_organization("Acme")
    recruiter = await make_user(org, roles=["recruiter"])
    seed = await seed_interview(
        admin_engine,
        app_db,
        org,
        recruiter,
        password=PASSWORD,
        settings=IDENTITY,
        text_answers=text_answers,
    )
    return seed, recruiter


async def desktop_for(client: AsyncClient, seed: Seeded) -> DesktopClient:
    desktop = DesktopClient(client, base_url=BASE)
    await desktop.login(seed.email, PASSWORD)
    await desktop.session_token(str(seed.interview_id))
    return desktop


async def test_the_contract_before_and_at_the_start_of_a_voice_interview(
    client: AsyncClient,
    app_db: Database,
    admin_engine: AsyncEngine,
    media: FakeMedia,
    make_organization: MakeOrganization,
    make_user: Any,
) -> None:
    seed, _ = await seeded(admin_engine, app_db, make_organization, make_user, text_answers=False)
    desktop = await desktop_for(client, seed)
    interview = str(seed.interview_id)

    briefing = await desktop.briefing(interview)
    assert briefing["answer_mode"] == "voice" and briefing["third_eye"] == "optional"
    assert briefing["notice"]["version"] and briefing["instructions"]
    assert "microphone" in briefing["mandatory_checks"]
    unknown = await desktop.interview(
        "POST",
        interview,
        "system-checks",
        {"app_version": "1.4.0", "os": "W", "results": [{"check": "gpu", "status": "pass"}]},
    )
    assert unknown.status_code == 422 and unknown.json()["code"] == "unknown-check"
    outdated = await desktop.interview(
        "POST", interview, "consents", {"notice_version": "2001-01-01", "items": []}
    )
    assert outdated.status_code == 409 and outdated.json()["code"] == "notice-outdated"
    asked = await desktop.request_accommodation(interview, ["extended_time"], "dyslexia")
    assert asked["status"] == "requested"
    no_check = await desktop.interview(
        "POST",
        interview,
        "start",
        {"system_check_id": str(UUID(int=1)), "consent_id": str(UUID(int=2))},
    )
    assert no_check.status_code == 409 and no_check.json()["code"] == "checks-incomplete"

    check = await desktop.system_check(interview, briefing["mandatory_checks"])
    assert check["passed"] and check["failed_mandatory"] == []
    consent = await desktop.consent(interview, briefing["notice"])
    assert consent["complete"] and consent["missing"] == []
    started = await desktop.start(interview, check["id"], consent["id"])
    assert started["room"] == f"iv-{interview}"
    assert started["participant_identity"].startswith("candidate-")
    assert started["participant_token"] and started["livekit_url"] == media.url
    state = started["state"]
    assert state["status"] == "in_progress" and state["answer_mode"] == "voice"
    assert state["stage"] == "start" and state["voice"] == "waiting" and state["question"] is None
    assert 0 < state["remaining_seconds"] <= 30 * 60
    assert media.dispatches == [f"iv-{interview}"]
    assert (await desktop.state(interview))["status"] == "in_progress"
    # Nothing is open until the agent begins.
    early = await desktop.answer(interview, str(UUID(int=3)), "hello")
    assert early.status_code == 409 and early.json()["code"] == "question-not-current"
    other = await desktop.call(
        "GET",
        f"/interviews/{UUID(int=4)}/session",
        token=desktop.session_tokens[interview],
    )
    assert other.status_code == 403 and other.json()["code"] == "wrong-interview"
    done = await desktop.complete(interview, "candidate_ended")
    assert done == {"status": "completed"}


@pytest.mark.parametrize("name", PERSONAS)
async def test_every_persona_finishes_a_full_interview(
    name: str,
    client: AsyncClient,
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user: Any,
    signed_in: Any,
) -> None:
    seed, recruiter = await seeded(admin_engine, app_db, make_organization, make_user)
    desktop = await desktop_for(client, seed)
    report = await simulate(desktop, str(seed.interview_id), persona(name, seed.knowledge))
    assert report.finished, report.final_state
    assert report.final_state["voice"] == "ended" and report.final_state["question"] is None
    kinds = [e.question_type for e in report.exchanges]
    assert kinds[0] == "introduction" and kinds[-1] == "final"

    browser = await signed_in(seed.organization_id, recruiter)
    transcript = (await browser.get(f"/api/v1/interviews/{seed.interview_id}/transcript")).json()
    assert transcript["status"] == "completed" and transcript["stage"] == "evaluation"
    required = [c for c in transcript["coverage"] if c["required"]]
    assert {c["skill"] for c in required} == {"Python", "PostgreSQL"}
    assert all(c["covered"] for c in required), transcript["coverage"]
    assert {s["speaker"] for s in transcript["segments"]} == {"ai", "candidate"} or name == "silent"
    mains = [q for q in transcript["questions"] if q["kind"] == "main"]
    assert mains and all(q["source"] in ("library", "resume", "generated", "pinned") for q in mains)
    resume = [q for q in mains if q["source"] == "resume"]
    assert resume and resume[0]["source_ref"]["field"] == "projects"

    async with app_db.tenant(seed.organization_id) as session:
        flags = {
            flag
            for answer in (
                await session.scalars(
                    select(InterviewAnswer).where(InterviewAnswer.interview_id == seed.interview_id)
                )
            ).all()
            for flag in answer.flags
        }
    if name == "adversarial":
        assert "manipulation" in flags
    if name == "cheating":
        assert {"ai_text_suspected", "repeated_answer"} <= flags
        assert report.refusals and all(r == "409 question-not-current" for r in report.refusals)
    if name == "strong":
        spoken = " ".join(s["text"] for s in transcript["segments"] if s["speaker"] == "ai")
        assert "five working days" in spoken  # the FAQ, and only the FAQ, answered it
    if name in ("strong", "partial"):
        assert "manipulation" not in flags


async def test_the_recruiter_decides_accommodations_before_the_interview(
    client: AsyncClient,
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user: Any,
    signed_in: Any,
) -> None:
    seed, recruiter = await seeded(
        admin_engine, app_db, make_organization, make_user, text_answers=False
    )
    desktop = await desktop_for(client, seed)
    interview = str(seed.interview_id)
    asked = await desktop.request_accommodation(interview, ["text_answers", "breaks"], "RSI")
    browser = await signed_in(seed.organization_id, recruiter)
    listed = (await browser.get(f"/api/v1/interviews/{interview}/accommodations")).json()
    assert [(a["id"], a["status"]) for a in listed] == [(asked["id"], "requested")]
    path = f"/api/v1/interviews/{interview}/accommodations/{asked['id']}/decision"
    extra = await browser.post(path, json={"approved": ["extended_time"]})
    assert extra.status_code == 422 and extra.json()["code"] == "not-requested"
    decided = await browser.post(path, json={"approved": ["text_answers"], "note": "Approved"})
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "approved" and decided.json()["approved_kinds"] == [
        "text_answers"
    ]
    again = await browser.post(path, json={"approved": []})
    assert again.status_code == 409 and again.json()["code"] == "already-decided"
    briefing = await desktop.briefing(interview)
    assert briefing["answer_mode"] == "text"
    assert briefing["accommodations"] == {
        "requested": ["text_answers", "breaks"],
        "approved": ["text_answers"],
    }


async def test_the_interview_briefing_is_the_organisations_to_set(
    app_db: Database, make_organization: MakeOrganization, make_user: Any, signed_in: Any
) -> None:
    org = await make_organization("Acme")
    admin = await make_user(org, roles=["org_admin"])
    browser = await signed_in(org, admin)
    assert (await browser.get("/api/v1/organization/interview-briefing")).json() == {
        "instructions": [],
        "faq": [],
    }
    body = {
        "instructions": ["  Join from a quiet room.  ", ""],
        "faq": [{"question": "Is the role remote?", "answer": "Hybrid."}],
    }
    saved = await browser.put("/api/v1/organization/interview-briefing", json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["instructions"] == ["Join from a quiet room."]
    twice = {"faq": [body["faq"][0], {"question": "is the role remote?", "answer": "No."}]}
    duplicate = await browser.put("/api/v1/organization/interview-briefing", json=twice)
    assert duplicate.status_code == 422 and duplicate.json()["code"] == "faq-duplicate"


async def test_livekits_webhook_interrupts_and_redispatches(
    client: AsyncClient,
    app_db: Database,
    admin_engine: AsyncEngine,
    media: FakeMedia,
    make_organization: MakeOrganization,
    make_user: Any,
) -> None:
    seed, _ = await seeded(admin_engine, app_db, make_organization, make_user, text_answers=False)
    desktop = await desktop_for(client, seed)
    interview = str(seed.interview_id)
    briefing = await desktop.briefing(interview)
    check = await desktop.system_check(interview, briefing["mandatory_checks"])
    consent = await desktop.consent(interview, briefing["notice"])
    await desktop.start(interview, check["id"], consent["id"])

    def event(kind: str) -> str:
        return json.dumps(
            {"kind": kind, "interview_id": interview, "organization_id": str(seed.organization_id)}
        )

    forged = await client.post(
        "/api/v1/livekit/webhook", content=event("candidate_left"), headers={"Authorization": "x"}
    )
    assert forged.status_code == 401 and forged.json()["code"] == "webhook-invalid"
    signed = {"Authorization": "fake-signature"}
    left = await client.post("/api/v1/livekit/webhook", content=event("agent_left"), headers=signed)
    assert left.status_code == 204 and len(media.dispatches) == 2
    # A late delivery while the candidate is (back) in the room interrupts nothing.
    identity = media.tokens[-1].identity
    media.present.add(identity)
    departure = json.dumps({**json.loads(event("candidate_left")), "identity": identity})
    late = await client.post("/api/v1/livekit/webhook", content=departure, headers=signed)
    assert late.status_code == 204
    async with app_db.tenant(seed.organization_id) as session:
        assert (await session.get_one(Interview, seed.interview_id)).status == "in_progress"
    media.present.clear()
    gone = await client.post("/api/v1/livekit/webhook", content=departure, headers=signed)
    assert gone.status_code == 204
    async with app_db.tenant(seed.organization_id) as session:
        row = await session.get_one(Interview, seed.interview_id)
    assert row.status == "interrupted" and row.interrupted_at is not None
    resumed = await desktop.start(interview, check["id"], consent["id"])
    assert resumed["state"]["status"] == "in_progress"


async def _websocket(
    app: FastAPI, path: str, headers: dict[str, str], *, messages: int
) -> tuple[list[dict[str, Any]], int | None]:
    """Opens a websocket on the app in this event loop; returns what it sent and its close code."""
    inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    await inbox.put({"type": "websocket.connect"})
    received: list[dict[str, Any]] = []
    closed: list[int] = []
    enough = asyncio.Event()

    async def receive() -> dict[str, Any]:
        return await inbox.get()

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "websocket.send":
            received.append(json.loads(message["text"]))
            if len(received) >= messages:
                enough.set()
        elif message["type"] == "websocket.close":
            closed.append(int(message.get("code", 1000)))
            enough.set()

    route, _, query = path.partition("?")
    scope = {
        "type": "websocket",
        "asgi": {"version": "3.0"},
        "scheme": "ws",
        "path": route,
        "raw_path": route.encode(),
        "query_string": query.encode(),
        "root_path": "",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]
        + [(b"host", b"api.hirevion.localhost")],
        "client": ("127.0.0.1", 50000),
        "server": ("api.hirevion.localhost", 80),
        "subprotocols": [],
        "state": {},
    }
    task = asyncio.create_task(app(scope, receive, send))
    try:
        await asyncio.wait_for(enough.wait(), 10)
    finally:
        await inbox.put({"type": "websocket.disconnect", "code": 1000})
        try:
            await asyncio.wait_for(task, 5)
        except TimeoutError:
            task.cancel()
    return received, closed[0] if closed else None


async def test_the_live_events_need_an_allowed_origin_and_a_session_that_can_see_it(
    api: FastAPI,
    client: AsyncClient,
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user: Any,
) -> None:
    seed, recruiter = await seeded(admin_engine, app_db, make_organization, make_user)
    desktop = await desktop_for(client, seed)
    await simulate(desktop, str(seed.interview_id), persona("partial", seed.knowledge))
    path = f"/api/v1/ws/interviews/{seed.interview_id}"
    async with app_db.tenant(seed.organization_id) as session:
        token, _, _ = await create_session(
            session,
            user_id=recruiter,
            organization_id=seed.organization_id,
            ip=None,
            user_agent=None,
            settings=IDENTITY,
            now=__import__("datetime").datetime.now(__import__("datetime").UTC),
        )
    cookie = f"{SESSION_COOKIE}={token}; {CSRF_COOKIE}=x"
    _, code = await _websocket(
        api, path, {"origin": "https://evil.example", "cookie": cookie}, messages=1
    )
    assert code == 1008
    _, code = await _websocket(api, path, {"origin": ORIGIN}, messages=1)
    assert code == 4401
    other_org = await make_organization("Globex")
    outsider = await make_user(other_org, roles=["recruiter"])
    async with app_db.tenant(other_org) as session:
        foreign, _, _ = await create_session(
            session,
            user_id=outsider,
            organization_id=other_org,
            ip=None,
            user_agent=None,
            settings=IDENTITY,
            now=__import__("datetime").datetime.now(__import__("datetime").UTC),
        )
    _, code = await _websocket(
        api, path, {"origin": ORIGIN, "cookie": f"{SESSION_COOKIE}={foreign}"}, messages=1
    )
    assert code == 4403
    events, code = await _websocket(api, path, {"origin": ORIGIN, "cookie": cookie}, messages=5)
    assert code is None and len(events) >= 5
    assert {e["type"] for e in events} <= {
        "AI_SPEAKING",
        "QUESTION_STARTED",
        "ANSWER_RECEIVED",
        "INTERVIEW_COMPLETED",
    }
    later, _ = await _websocket(
        api, f"{path}?after={events[2]['id']}", {"origin": ORIGIN, "cookie": cookie}, messages=1
    )
    assert later[0]["id"] == events[3]["id"]  # a reconnect picks up after the last one seen
    async with admin_engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM transcript_segments")) > 0
