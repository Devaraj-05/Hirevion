"""The agent's side of an interview without a room (SP-09a and SP-09c): one agent per
interview, a replacement taking over after a crash with no lost turn, and voice turns through
the bridge with the `hv.state` the desktop shows.

Exit criterion: a killed agent resumes within 10 s.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.db.session import Database
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.interview_session import preparation
from hirevion_core.interview_session.briefing import NOTICE_VERSION, notice_items
from hirevion_core.interview_session.conductor import Conductor
from hirevion_core.interview_session.media import FakeMedia
from hirevion_core.interview_session.preparation import CheckReport, ConsentAnswer
from hirevion_core.interviews.lifecycle import By
from hirevion_core.models import CandidateAccount, Interview
from hirevion_interview_agent.bridge import InterviewBridge, state_message
from hirevion_interview_agent.lock import REFRESH_SECONDS, TTL_SECONDS, AgentLock
from hirevion_interview_simulator.seed import seed_interview

pytestmark = pytest.mark.db

IDENTITY = IdentitySettings(hibp_enabled=False)
MakeOrganization = Callable[[str], Awaitable[UUID]]


def test_a_replacement_agent_can_take_over_within_ten_seconds() -> None:
    # The dead agent's lock lapses after its TTL; the replacement polls every quarter second.
    assert TTL_SECONDS + 0.25 <= 10
    assert REFRESH_SECONDS * 2 < TTL_SECONDS  # one missed refresh doesn't lose the lock


async def test_one_agent_holds_an_interview_until_it_dies(valkey: Redis) -> None:
    interview = UUID(int=7)
    first = AgentLock(valkey, interview, "job-a", ttl=2)
    assert await first.acquire(wait=0)
    second = AgentLock(valkey, interview, "job-b", ttl=2)
    assert not await second.acquire(wait=0.5)
    # The first agent's process dies: no release, no more refreshes.
    assert first._refresher is not None
    first._refresher.cancel()
    started = asyncio.get_running_loop().time()
    assert await second.acquire(wait=5)
    assert asyncio.get_running_loop().time() - started < 3
    await second.release()
    assert await valkey.get(f"hv:iv:{interview}:agent") is None


async def test_a_lock_another_agent_took_is_reported_lost(
    valkey: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hirevion_interview_agent import lock as lock_module

    monkeypatch.setattr(lock_module, "REFRESH_SECONDS", 0.05)
    interview = UUID(int=8)
    mine = AgentLock(valkey, interview, "job-a", ttl=5)
    assert await mine.acquire(wait=0)
    # The key lapsed and another agent took it.
    await valkey.set(f"hv:iv:{interview}:agent", "job-b", ex=5)
    await asyncio.wait_for(mine.lost.wait(), 2)
    # A lapse nobody else took is simply taken back.
    again = AgentLock(valkey, UUID(int=9), "job-c", ttl=5)
    assert await again.acquire(wait=0)
    await valkey.delete(f"hv:iv:{UUID(int=9)}:agent")
    await asyncio.sleep(0.2)
    assert not again.lost.is_set()
    assert await valkey.get(f"hv:iv:{UUID(int=9)}:agent") in ("job-c", b"job-c")
    await again.release()


async def _voice_interview(
    admin_engine: AsyncEngine, app_db: Database, valkey: Redis, org: UUID, recruiter: UUID
) -> UUID:
    seed = await seed_interview(
        admin_engine,
        app_db,
        org,
        recruiter,
        password="x" * 20,
        settings=IDENTITY,
        text_answers=False,
    )
    async with app_db.tenant(org) as session:
        interview = await session.get_one(Interview, seed.interview_id)
        checks = [CheckReport(c, "pass") for c in interview.policy["mandatory_checks"]]
        check = await preparation.record_system_check(
            session, interview, app_version="1.4.0", os="W", results=checks
        )
        consent = await preparation.record_consent(
            session,
            interview,
            notice_version=NOTICE_VERSION,
            answers=[ConsentAnswer(i.purpose, True) for i in notice_items(interview.policy)],
            ip=None,
            user_agent=None,
        )
        account = await session.get_one(CandidateAccount, interview.candidate_account_id)
    api = Conductor(app_db, valkey, llm=None, media=FakeMedia())
    await api.start(
        org,
        seed.interview_id,
        account_id=account.id,
        system_check_id=check.id,
        consent_id=consent.id,
        token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        by=By("candidate", "test"),
    )
    return seed.interview_id


async def test_a_replacement_agent_resumes_the_open_question(
    app_db: Database,
    admin_engine: AsyncEngine,
    valkey: Redis,
    make_organization: MakeOrganization,
    make_user: Any,
) -> None:
    org = await make_organization("Acme")
    recruiter = await make_user(org, roles=["recruiter"])
    interview_id = await _voice_interview(admin_engine, app_db, valkey, org, recruiter)

    first = InterviewBridge(Conductor(app_db, valkey, llm=None), org, interview_id, job_id="AJ_1")
    greeting = await first.begin()
    assert greeting is not None and greeting.text.startswith("Hello")
    assert greeting.state["question"]["type"] == "introduction"
    assert greeting.state["voice"] == "waiting"
    now = datetime.now(UTC)
    turn = await first.heard(
        "I build Python services and run PostgreSQL in production.",
        started_at=now,
        ended_at=now + timedelta(seconds=4),
        confidence=0.88,
        acknowledged=True,
    )
    assert turn is not None and turn.state["question"]["type"] != "introduction"
    assert not turn.text.startswith(("Thanks", "Got it", "Okay", "Thank you", "Understood"))
    open_question = turn.state["question"]

    # The first agent crashes here; a second one (another process) begins and recovers.
    second = InterviewBridge(Conductor(app_db, valkey, llm=None), org, interview_id, job_id="AJ_2")
    recovered = await second.begin()
    assert recovered is not None
    assert recovered.text.startswith("Sorry about that")
    assert open_question["text"] in recovered.text
    assert recovered.state["question"]["id"] == open_question["id"]  # no lost or repeated turn
    assert await second.control("repeat") is not None
    assert await second.control("done_answering") is None
    shown = await second.voice("speaking")
    assert shown is not None and shown["voice"] == "speaking"
    assert (await second.conductor.session_state(org, interview_id)).voice == "speaking"
    # The desktop ends the interview: the agent notices on its next tick, and leaves.
    assert not await second.ended()
    await second.conductor.complete(org, interview_id, "candidate_ended", by=By("candidate", "t"))
    assert await second.ended()


def test_the_state_message_has_the_contracts_shape() -> None:
    from hirevion_core.interview_session.conductor import QuestionView, SessionView

    view = SessionView(
        status="in_progress",
        started_at=None,
        deadline_at=None,
        remaining_seconds=1830,
        third_eye="optional",
        workspace="code",
        answer_mode="voice",
        question=QuestionView("q", 3, "Write a function", "coding", 600, "code", ["python"]),
        voice="listening",
        stage="coding",
        message=None,
        notice={"kind": "camera_covered"},
    )
    assert state_message(view, "thinking") == {
        "voice": "thinking",
        "question": {
            "id": "q",
            "index": 3,
            "text": "Write a function",
            "type": "coding",
            "time_limit_seconds": 600,
            "workspace": "code",
            "languages": ["python"],
        },
        "remaining_seconds": 1830,
        "notice": {"kind": "camera_covered"},
    }


async def test_the_nudge_relay_backs_off_while_valkey_is_down(
    valkey: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hirevion_core.proctoring import nudges
    from hirevion_interview_agent import bridge as bridge_module
    from hirevion_interview_agent.bridge import MAX_BACKOFF_SECONDS, relay_nudges

    delays: list[float] = []
    stop = asyncio.Event()

    async def read(*_: Any, **__: Any) -> Any:
        raise ConnectionError("Valkey is down")

    async def publish(_: Any) -> None:
        return None

    async def no_sleep(seconds: float) -> None:
        delays.append(seconds)
        if len(delays) >= 9:
            stop.set()

    monkeypatch.setattr(nudges, "read", read)
    monkeypatch.setattr(bridge_module.asyncio, "sleep", no_sleep)
    fake: Any = type("Bridge", (), {"interview_id": UUID(int=3)})()
    await relay_nudges(valkey, fake, publish, stop)  # type: ignore[arg-type]
    assert delays[:4] == [1.0, 2.0, 4.0, 8.0]
    assert max(delays) == MAX_BACKOFF_SECONDS and delays[-1] == MAX_BACKOFF_SECONDS


async def test_a_proctoring_nudge_reaches_the_desktop_as_a_state_notice(
    app_db: Database,
    admin_engine: AsyncEngine,
    valkey: Redis,
    make_organization: MakeOrganization,
    make_user: Any,
) -> None:
    from hirevion_core.proctoring import nudges
    from hirevion_interview_agent.bridge import relay_nudges

    org = await make_organization("Acme")
    recruiter = await make_user(org, roles=["recruiter"])
    interview_id = await _voice_interview(admin_engine, app_db, valkey, org, recruiter)
    bridge = InterviewBridge(Conductor(app_db, valkey, llm=None), org, interview_id, job_id="AJ_1")
    await bridge.begin()
    # A nudge from before the agent started is already in the state the desktop reads.
    old = nudges.Nudge("e0", "focus_lost", "WINDOW_MINIMIZED", "WARNING", "2026-10-12T05:00:00Z")
    await nudges.deliver(valkey, interview_id, old)

    sent: list[dict[str, Any]] = []
    stop = asyncio.Event()

    async def publish(state: dict[str, Any] | None) -> None:
        assert state is not None
        sent.append(state)
        stop.set()

    relay = asyncio.create_task(relay_nudges(valkey, bridge, publish, stop, block_ms=200))
    await asyncio.sleep(0.3)
    fresh = nudges.Nudge(
        "e1", "camera_covered", "CAMERA_OBSTRUCTED", "CRITICAL", "2026-10-12T05:01Z"
    )
    await nudges.deliver(valkey, interview_id, fresh)
    await asyncio.wait_for(relay, 5)
    assert len(sent) == 1
    state = sent[0]
    assert state["notice"]["kind"] == "camera_covered" and state["notice"]["severity"] == "CRITICAL"
    assert state["notice"]["text"] and state["question"] is not None and "voice" in state
