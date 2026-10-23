"""The coding console over HTTP (SP-16; `docs/api/contracts/coding.md`): the desktop fetches the
coding question, saves and submits code that is never run, and sends integrity events; the
interview moves on after the submission or the time limit; the evaluation reviews the code; the
coding report and Candidate 360 show it."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_api.app import create_app
from hirevion_api.settings import ApiSettings
from hirevion_core.ai import build_ai
from hirevion_core.ai.settings import AiSettings
from hirevion_core.db.session import Database
from hirevion_core.evaluation.offline import offline_llm
from hirevion_core.evaluation.service import evaluate_interview
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.interview_session import realtime
from hirevion_core.interview_session.media import FakeMedia
from hirevion_core.models import CodingSubmission, CodingTelemetry, InterviewAnswer
from hirevion_interview_simulator.client import DesktopClient
from hirevion_interview_simulator.coding import CODING_QUESTION
from hirevion_interview_simulator.personas import persona
from hirevion_interview_simulator.run import simulate
from hirevion_interview_simulator.seed import Seeded, seed_interview

pytestmark = pytest.mark.db

BASE = "http://api.hirevion.localhost"
ORIGIN = "https://app.hirevion.localhost"
IDENTITY = IdentitySettings(hibp_enabled=False, web_origin=ORIGIN)
PASSWORD = "a long simulated passphrase"  # noqa: S105 (a test password)
MakeOrganization = Callable[[str], Awaitable[UUID]]
GOOD = (
    "def solve(nums, target):\n"
    "    # One pass with a hash map.\n"
    "    if not nums:\n"
    "        return []\n"
    "    seen = {}\n"
    "    for index, value in enumerate(nums):\n"
    "        if target - value in seen:\n"
    "            return [seen[target - value], index]\n"
    "        seen[value] = index\n"
    "    return []\n"
)


@pytest.fixture
def api(app_db: Database, valkey: Redis) -> FastAPI:
    return create_app(
        ApiSettings(allowed_origins=ORIGIN, run_workers=False, ip_rate_limit=100_000),
        db=app_db,
        redis=valkey,
        identity=IDENTITY,
        ai=build_ai(AiSettings(profile="mock"), app_db),
        media=FakeMedia(),
    )


@pytest.fixture
def client(api: FastAPI, client_for: Callable[[FastAPI], AsyncClient]) -> AsyncClient:
    return client_for(api)


async def seeded(
    admin_engine: AsyncEngine, app_db: Database, make_organization: MakeOrganization, make_user: Any
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
        coding=True,
        duration_minutes=45,
    )
    return seed, recruiter


async def desktop_for(client: AsyncClient, seed: Seeded) -> DesktopClient:
    desktop = DesktopClient(client, base_url=BASE)
    await desktop.login(seed.email, PASSWORD)
    await desktop.session_token(str(seed.interview_id))
    return desktop


async def to_coding(desktop: DesktopClient, interview_id: str) -> dict[str, Any]:
    """Starts the interview and answers until the coding question is open; returns the state."""
    briefing = await desktop.briefing(interview_id)
    check = await desktop.system_check(interview_id, briefing["mandatory_checks"])
    consent = await desktop.consent(interview_id, briefing["notice"])
    state = (await desktop.start(interview_id, check["id"], consent["id"]))["state"]
    answerer = persona("strong")
    for _ in range(40):
        question = state["question"]
        if question["workspace"] == "code":
            return state
        response = await desktop.answer(interview_id, question["id"], answerer.answer(question))
        assert response.status_code == 202, response.text
        state = response.json()["state"]
    raise AssertionError("the coding question never came")


async def test_the_console_gets_the_question_saves_submits_and_moves_on(
    client: AsyncClient,
    app_db: Database,
    valkey: Redis,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user: Any,
) -> None:
    seed, _ = await seeded(admin_engine, app_db, make_organization, make_user)
    desktop = await desktop_for(client, seed)
    iv = str(seed.interview_id)
    state = await to_coding(desktop, iv)
    question = state["question"]
    assert "text box" in (state["message"] or "") and "Submit" in (state["message"] or "")

    view = (await desktop.interview("GET", iv, "coding")).json()["question"]
    assert view["question_id"] == question["id"] and view["text"] == CODING_QUESTION
    assert view["languages"] == ["python", "javascript"]
    assert view["starter_code"]["python"].startswith("def solve(")
    assert view["draft"] is None and view["time_limit_seconds"] > 0

    saved = await desktop.workspace(iv, question["id"], "def solve(nums, target):\n    pass\n")
    assert saved.status_code == 202
    view = (await desktop.interview("GET", iv, "coding")).json()["question"]
    draft = view["draft"]
    assert draft["content"].startswith("def solve") and draft["language"] == "python"

    now = datetime.now(UTC).isoformat()
    events = [
        {"kind": "focus", "at": now},
        {"kind": "typing_started", "at": now},
        {"kind": "paste", "at": now, "chars": 42},
        {"kind": "blur", "at": now},
    ]
    sent = await desktop.interview(
        "POST", iv, "coding/telemetry", {"question_id": question["id"], "events": events}
    )
    assert sent.status_code == 202 and sent.json() == {"accepted": 4}

    for body, status, code in (
        ({"kind": "keystroke", "at": now}, 422, None),
        ({"kind": "paste", "at": now}, 422, "invalid-chars"),
        ({"kind": "paste", "at": now, "chars": 3, "text": "secret"}, 422, None),
        (
            {"kind": "focus", "at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()},
            422,
            "event-out-of-time",
        ),
    ):
        refused = await desktop.interview(
            "POST", iv, "coding/telemetry", {"question_id": question["id"], "events": [body]}
        )
        assert refused.status_code == status, refused.text
        if code:
            assert refused.json()["code"] == code

    wrong = await desktop.interview(
        "POST",
        iv,
        "coding/submissions",
        {"question_id": question["id"], "language": "sql", "code": GOOD},
    )
    assert wrong.status_code == 422 and wrong.json()["code"] == "language-not-offered"
    huge = await desktop.interview(
        "POST",
        iv,
        "coding/submissions",
        {"question_id": question["id"], "language": "python", "code": "x" * 300_000},
    )
    assert huge.status_code in (413, 422)

    submitted = await desktop.interview(
        "POST",
        iv,
        "coding/submissions",
        {"question_id": question["id"], "language": "python", "code": GOOD},
    )
    assert submitted.status_code == 202, submitted.text
    body = submitted.json()
    assert body["submission"]["language"] == "python" and body["submission"]["size"] == len(GOOD)
    assert body["submission"]["source"] == "submitted"
    assert body["state"]["question"]["type"] == "final"  # the interview moved on

    again = await desktop.interview(
        "POST",
        iv,
        "coding/submissions",
        {"question_id": question["id"], "language": "python", "code": GOOD},
    )
    assert again.status_code == 409 and again.json()["code"] == "question-not-current"
    assert (await desktop.interview("GET", iv, "coding")).json() == {"question": None}

    async with app_db.tenant(seed.organization_id) as session:
        [row] = (await session.scalars(select(CodingSubmission))).all()
        assert row.code == GOOD and row.source == "submitted" and len(row.sha256) == 64
        kinds = [t.kind for t in (await session.scalars(select(CodingTelemetry))).all()]
        assert kinds == ["focus", "typing_started", "paste", "blur"]
        answer = await session.scalar(
            select(InterviewAnswer).where(InterviewAnswer.question_id == UUID(question["id"]))
        )
        assert answer is not None and answer.analysis["source"] == "coding"
    events_seen = [e.type for e in await realtime.read(valkey, seed.interview_id)]
    assert "CODE_SUBMITTED" in events_seen


async def test_the_time_limit_keeps_the_last_saved_text_as_the_final_code(
    client: AsyncClient,
    api: FastAPI,
    app_db: Database,
    valkey: Redis,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user: Any,
) -> None:
    seed, _ = await seeded(admin_engine, app_db, make_organization, make_user)
    desktop = await desktop_for(client, seed)
    iv = str(seed.interview_id)
    state = await to_coding(desktop, iv)
    question = state["question"]
    await desktop.workspace(iv, question["id"], GOOD, language="python")
    from hirevion_core.interview_session.conductor import Conductor
    from hirevion_core.interviews.lifecycle import By

    later = datetime.now(UTC) + timedelta(seconds=question["time_limit_seconds"] + 120)
    conductor = Conductor(app_db, valkey, llm=None, media=FakeMedia(), clock=lambda: later)
    turn = await conductor.tick(seed.organization_id, seed.interview_id, by=By.system())
    assert turn is not None and turn.view.question is not None
    assert turn.view.question.type == "final"
    async with app_db.tenant(seed.organization_id) as session:
        [row] = (await session.scalars(select(CodingSubmission))).all()
    assert row.source == "time_limit" and row.code == GOOD


async def test_every_persona_with_coding_finishes_and_the_code_is_reviewed(
    client: AsyncClient,
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user: Any,
    signed_in: Any,
) -> None:
    seed, recruiter = await seeded(admin_engine, app_db, make_organization, make_user)
    desktop = await desktop_for(client, seed)
    report = await simulate(desktop, str(seed.interview_id), persona("strong", seed.knowledge))
    assert report.finished, report.final_state
    assert any(e.question_type == "coding" for e in report.exchanges)

    llm, _ = offline_llm()
    evaluation = await evaluate_interview(app_db, llm, seed.organization_id, seed.interview_id)
    assert evaluation is not None and evaluation.status == "ready"
    coding = evaluation.summary["coding"]
    assert coding["status"] == "scored" and coding["score"] >= 7.0
    [reviewed] = coding["questions"]
    assert reviewed["criteria"]["time_complexity"]["estimated"] is True
    assert all(c["evidence"] for c in reviewed["criteria"].values())
    assert evaluation.pinned["coding_prompt_version"] == "evaluation-coding-v1"

    browser = await signed_in(seed.organization_id, recruiter)
    api_view = (await browser.get(f"/api/v1/interviews/{seed.interview_id}/evaluation")).json()[
        "evaluation"
    ]
    assert api_view["coding"]["status"] == "scored"
    assert api_view["coding"]["questions"][0]["criteria"]["correctness"]["evidence"]
    document = (await browser.get(f"/api/v1/interviews/{seed.interview_id}/reports/coding")).json()
    sections = {s["key"]: s for s in document["sections"]}
    assert sections["final_code"]["status"] == "populated"
    assert sections["assessment"]["status"] == "populated"
    assert sections["integrity"]["status"] == "populated"
    assert all(s["status"] != "pending" for s in document["sections"])
