"""The conductor against the database (SP-09 Task 3): preparation, starting in text and voice
modes, turns with their rows, interruptions and the resume policy, a restart mid-interview, and
the transcript's artifacts."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.access.actor import Actor
from hirevion_core.access.errors import Conflict, Gone, Invalid, NotFound, TooLarge
from hirevion_core.access.scope import ResourceScope
from hirevion_core.ai import build_ai
from hirevion_core.ai.settings import AiSettings
from hirevion_core.db.session import Database
from hirevion_core.engine.planner import said
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.ids import uuid7
from hirevion_core.interview_session import preparation, realtime
from hirevion_core.interview_session.briefing import NOTICE_VERSION, briefing, notice_items
from hirevion_core.interview_session.conductor import Conductor, Speech
from hirevion_core.interview_session.media import FakeMedia, candidate_identity
from hirevion_core.interview_session.preparation import CheckReport, ConsentAnswer
from hirevion_core.interview_session.transcripts import render_vtt, write_artifacts
from hirevion_core.interviews import assignment
from hirevion_core.interviews.assignment import Assignment
from hirevion_core.interviews.lifecycle import By
from hirevion_core.interviews.plan import write_plan
from hirevion_core.interviews.scheduler import run_due
from hirevion_core.models import (
    Application,
    CandidateAccount,
    Interview,
    InterviewAnswer,
    InterviewQuestion,
    InterviewSession,
    Transcript,
    TranscriptSegment,
)
from hirevion_core.storage.paths import BlobPath

pytestmark = pytest.mark.db

SETTINGS = IdentitySettings(hibp_enabled=False)
MakeOrganization = Callable[[str], Awaitable[UUID]]
CANDIDATE = By("candidate", "test")
LAPTOP = "laptop-key-thumbprint"
OLD_RESUME = {"grace_seconds": 300, "max_interruptions": 3, "pause_timer": True}
STRONG = (
    "I would reuse connections from a pool with a maximum size, a wait timeout when it is "
    "exhausted, health checks before handing a connection out, and metrics on the queue so the "
    "pool is sized against the database's own connection limit and the service's concurrency."
)
ALL_CHECKS = [
    CheckReport(name, "pass")
    for name in (
        "camera",
        "microphone",
        "speaker",
        "screen_capture",
        "network",
        "displays",
        "privacy",
        "media_foundation",
        "webview2",
    )
]


@dataclass
class Scene:
    organization_id: UUID
    interview_id: UUID
    account_id: UUID
    recruiter: Actor
    application_id: UUID


class Blobs:
    def __init__(self) -> None:
        self.files: dict[str, tuple[bytes, str]] = {}

    async def put(self, path: BlobPath, data: bytes, content_type: str) -> None:
        self.files[str(path)] = (data, content_type)

    async def get(self, path: BlobPath) -> bytes:
        return self.files[str(path)][0]

    async def delete(self, path: BlobPath) -> None:
        self.files.pop(str(path), None)


async def invited(
    app_db: Database,
    make_hiring: Any,
    organization_id: UUID,
    *,
    starts_at: datetime | None = None,
) -> Scene:
    hiring = await make_hiring(organization_id)
    actor = Actor(hiring.recruiter_id, organization_id, frozenset(permissions_for(["recruiter"])))
    now = datetime.now(UTC)
    opens = starts_at or now - timedelta(minutes=5)
    async with app_db.tenant(organization_id) as session:
        result = await assignment.assign(
            session,
            actor,
            Assignment(
                application_ids=[hiring.application_id],
                template_id=hiring.template_id,
                starts_at=opens,
                expires_at=max(opens, now) + timedelta(days=1),
            ),
            ResourceScope(actor.user_id, organization_wide=True, team_ids=frozenset()),
            settings=SETTINGS,
        )
        [interview] = result.created
        account_id = await session.scalar(
            select(CandidateAccount.id).where(CandidateAccount.candidate_id == hiring.candidate_id)
        )
    assert account_id is not None
    return Scene(organization_id, interview.id, account_id, actor, hiring.application_id)


async def prepare(
    app_db: Database, scene: Scene, *, accommodations: list[str] | None = None
) -> tuple[UUID, UUID]:
    """Approves any accommodations, then passes the system check and consents to everything."""
    async with app_db.tenant(scene.organization_id) as session:
        interview = await session.get_one(Interview, scene.interview_id)
        if accommodations:
            request = await preparation.request_accommodation(
                session, interview, accommodations, "please", CANDIDATE
            )
            await preparation.decide_accommodation(
                session, scene.recruiter, interview, request.id, approved=accommodations, note=None
            )
        check = await preparation.record_system_check(
            session, interview, app_version="1.4.0", os="Windows 11", results=ALL_CHECKS
        )
        consent = await preparation.record_consent(
            session,
            interview,
            notice_version=NOTICE_VERSION,
            answers=[ConsentAnswer(i.purpose, True) for i in notice_items(interview.policy)],
            ip="127.0.0.1",
            user_agent="test",
        )
    return check.id, consent.id


class Answering:
    """A clock that moves on as the candidate answers: an interview lasts its whole length
    (product owner, 2026-11-16), so instant answers would never reach its end."""

    def __init__(self) -> None:
        self.offset = timedelta()

    def now(self) -> datetime:
        return datetime.now(UTC) + self.offset

    def answered(self) -> None:
        self.offset += timedelta(minutes=2)


def conductor(
    app_db: Database,
    valkey: Redis,
    media: FakeMedia | None = None,
    clock: Answering | None = None,
) -> Conductor:
    kwargs = {"clock": clock.now} if clock else {}
    return Conductor(app_db, valkey, llm=None, media=media or FakeMedia(), **kwargs)


async def start(
    cond: Conductor,
    scene: Scene,
    check: UUID | None,
    consent: UUID | None,
    *,
    device: str | None = LAPTOP,
) -> Any:
    return await cond.start(
        scene.organization_id,
        scene.interview_id,
        account_id=scene.account_id,
        system_check_id=check,
        consent_id=consent,
        token_expires_at=datetime.now(UTC) + timedelta(hours=2),
        by=CANDIDATE,
        device_jkt=device,
    )


async def use_policy(admin_engine: AsyncEngine, scene: Scene, resume: dict[str, Any]) -> None:
    """Gives the interview another resume policy, as an interview assigned before C8-9 has."""
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE interviews SET policy = jsonb_set(policy, '{resume}', "
                "CAST(:resume AS jsonb)) WHERE id = :id"
            ),
            {"resume": json.dumps(resume), "id": scene.interview_id},
        )


def reply(view: Any) -> str:
    question = view.question
    assert question is not None
    if question.type == "introduction":
        return "I'm a backend engineer who builds Python services and tunes PostgreSQL."
    if question.type == "final":
        return "No, that's all, thank you."
    return STRONG


async def finish_in_text(
    cond: Conductor, scene: Scene, view: Any, clock: Answering, limit: int = 40
) -> Any:
    for _ in range(limit):
        if view.status != "in_progress":
            return view
        clock.answered()
        result = await cond.answer(
            scene.organization_id,
            scene.interview_id,
            UUID(view.question.id),
            reply(view),
            mode="text",
            by=CANDIDATE,
        )
        view = result.view
    raise AssertionError("the interview never finished")


async def test_the_briefing_follows_the_policy_and_its_accommodations(
    app_db: Database, make_organization: MakeOrganization, make_hiring: Any
) -> None:
    scene = await invited(app_db, make_hiring, await make_organization("Acme"))
    async with app_db.tenant(scene.organization_id) as session:
        interview = await session.get_one(Interview, scene.interview_id)
        before = await briefing(session, interview)
        assert before.answer_mode == "voice" and "microphone" in before.mandatory_checks
        purposes = {item.purpose: item.required for item in before.notice}
        assert purposes["transcript"] and purposes["camera"] and purposes["proctoring_events"]
        assert purposes["third_eye"] is False  # optional in this template
        assert len(before.instructions) >= 5
        request = await preparation.request_accommodation(
            session, interview, ["text_answers", "extended_time"], "RSI", CANDIDATE
        )
        await preparation.decide_accommodation(
            session, scene.recruiter, interview, request.id, approved=["text_answers"], note="ok"
        )
        after = await briefing(session, interview)
    assert after.answer_mode == "text" and "microphone" not in after.mandatory_checks
    assert after.requested == ["text_answers", "extended_time"]
    assert after.approved == ["text_answers"]
    assert after.duration_minutes == 45  # extended time wasn't approved


async def test_checks_and_consents_are_validated(
    app_db: Database, make_organization: MakeOrganization, make_hiring: Any
) -> None:
    scene = await invited(app_db, make_hiring, await make_organization("Acme"))
    async with app_db.tenant(scene.organization_id) as session:
        interview = await session.get_one(Interview, scene.interview_id)
        warned = [c if c.check != "network" else CheckReport("network", "warn") for c in ALL_CHECKS]
        result = await preparation.record_system_check(
            session, interview, app_version="1.4.0", os="Windows", results=warned
        )
        assert not result.passed and result.failed_mandatory == ["network"]
        with pytest.raises(Invalid, match="unknown-check"):
            await preparation.record_system_check(
                session, interview, app_version="1", os="W", results=[CheckReport("gpu", "pass")]
            )
        with pytest.raises(Conflict, match="notice-outdated"):
            await preparation.record_consent(
                session,
                interview,
                notice_version="2020-01-01",
                answers=[],
                ip=None,
                user_agent=None,
            )
        declined = await preparation.record_consent(
            session,
            interview,
            notice_version=NOTICE_VERSION,
            answers=[ConsentAnswer("camera", False), ConsentAnswer("transcript", True)],
            ip=None,
            user_agent=None,
        )
        assert not declined.complete and "camera" in declined.missing
        with pytest.raises(Invalid, match="unknown-purpose"):
            await preparation.record_consent(
                session,
                interview,
                notice_version=NOTICE_VERSION,
                answers=[ConsentAnswer("keystrokes", True)],
                ip=None,
                user_agent=None,
            )


async def test_a_text_interview_runs_to_completion_with_its_rows_and_events(
    app_db: Database,
    admin_engine: AsyncEngine,
    valkey: Redis,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    scene = await invited(app_db, make_hiring, await make_organization("Acme"))
    check, consent = await prepare(app_db, scene, accommodations=["text_answers"])
    media = FakeMedia()
    clock = Answering()
    cond = conductor(app_db, valkey, media, clock)
    started = await start(cond, scene, check, consent)
    assert started.view.status == "in_progress" and started.view.answer_mode == "text"
    assert started.view.question.type == "introduction"
    assert started.view.message.startswith("Hello")
    assert media.dispatches == []  # no agent in text mode
    assert started.media.room == f"iv-{scene.interview_id}"
    final = await finish_in_text(cond, scene, started.view, clock)
    assert final.status == "completed" and final.voice == "ended"

    async with app_db.tenant(scene.organization_id) as session:
        interview = await session.get_one(Interview, scene.interview_id)
        assert interview.status == "completed" and interview.completed_at is not None
        application = await session.get_one(Application, scene.application_id)
        assert application.stage == "interviewed"
        questions = (
            await session.scalars(
                select(InterviewQuestion)
                .where(InterviewQuestion.interview_id == scene.interview_id)
                .order_by(InterviewQuestion.position)
            )
        ).all()
        answers = (
            await session.scalars(
                select(InterviewAnswer).where(InterviewAnswer.interview_id == scene.interview_id)
            )
        ).all()
        segments = (
            await session.scalars(
                select(TranscriptSegment)
                .where(TranscriptSegment.interview_id == scene.interview_id)
                .order_by(TranscriptSegment.seq)
            )
        ).all()
        row = await session.get_one(InterviewSession, scene.interview_id)
        transcript = await session.get(Transcript, scene.interview_id)
    assert questions[0].kind == "introduction" and questions[-1].kind == "final"
    assert {q.kind for q in questions} >= {"introduction", "main", "final"}
    assert all(q.status in ("answered", "skipped", "timed_out") for q in questions)
    mains = [q for q in questions if q.kind == "main"]
    assert {q.skill for q in mains} == {"Python", "PostgreSQL"}
    assert all(q.source in ("library", "generated", "resume", "pinned") for q in mains)
    assert len(answers) == len(questions)
    assert {a.mode for a in answers} == {"text"}
    assert [s.seq for s in segments] == list(range(1, len(segments) + 1))
    assert {s.speaker for s in segments} == {"ai", "candidate"}
    assert row.state_seq >= len(answers) and row.ended_at is not None
    assert transcript is not None and transcript.status == "pending"

    async with admin_engine.connect() as conn:
        topics = (
            await conn.scalars(
                text(
                    "SELECT topic FROM outbox_events WHERE payload->>'interview_id' = :id "
                    "ORDER BY created_at"
                ),
                {"id": str(scene.interview_id)},
            )
        ).all()
    assert "interview.started" in topics and "interview.completed" in topics
    events = await realtime.read(valkey, scene.interview_id)
    kinds = {event.type for event in events}
    assert {"AI_SPEAKING", "QUESTION_STARTED", "ANSWER_RECEIVED", "INTERVIEW_COMPLETED"} <= kinds
    assert all("quality" not in event.data and "score" not in event.data for event in events)


async def test_a_voice_interview_dispatches_the_agent_which_begins_it(
    app_db: Database, valkey: Redis, make_organization: MakeOrganization, make_hiring: Any
) -> None:
    scene = await invited(app_db, make_hiring, await make_organization("Acme"))
    check, consent = await prepare(app_db, scene)
    media = FakeMedia()
    cond = conductor(app_db, valkey, media)
    started = await start(cond, scene, check, consent)
    assert started.view.answer_mode == "voice" and started.view.stage == "start"
    assert started.view.question is None
    assert media.dispatches == [f"iv-{scene.interview_id}"]
    assert started.media.identity.startswith("candidate-")
    agent = Conductor(app_db, valkey, llm=None, origin="agent:test")
    begun = await agent.begin(scene.organization_id, scene.interview_id, by=By("agent", "test"))
    assert begun.say.startswith("Hello") and begun.asked is not None
    spoken_at = datetime.now(UTC) + timedelta(seconds=10)
    turn = await agent.answer(
        scene.organization_id,
        scene.interview_id,
        None,
        "I'm a backend engineer.",
        mode="voice",
        by=CANDIDATE,
        speech=Speech(spoken_at - timedelta(seconds=3), spoken_at, 0.91),
    )
    assert turn.asked is not None and turn.asked.type != "introduction"
    async with app_db.tenant(scene.organization_id) as session:
        spoken = await session.scalar(
            select(TranscriptSegment).where(
                TranscriptSegment.interview_id == scene.interview_id,
                TranscriptSegment.speaker == "candidate",
            )
        )
    assert spoken is not None and float(spoken.confidence) == pytest.approx(0.91)
    assert spoken.end_ms - spoken.start_ms == pytest.approx(3000, abs=50)
    # A second start (the app restarted) reconnects without a second agent.
    await valkey.set(f"hv:iv:{scene.interview_id}:agent", "job", ex=8)
    again = await start(cond, scene, check, consent)
    assert again.resumed and media.dispatches == [f"iv-{scene.interview_id}"]


async def test_start_is_refused_until_everything_is_ready(
    app_db: Database,
    admin_engine: AsyncEngine,
    valkey: Redis,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    org = await make_organization("Acme")
    scene = await invited(app_db, make_hiring, org)
    check, consent = await prepare(app_db, scene)
    cond = conductor(app_db, valkey)
    async with app_db.tenant(org) as session:
        interview = await session.get_one(Interview, scene.interview_id)
        failed = await preparation.record_system_check(
            session, interview, app_version="1", os="W", results=[CheckReport("camera", "fail")]
        )
        partial = await preparation.record_consent(
            session, interview, notice_version=NOTICE_VERSION, answers=[], ip=None, user_agent=None
        )
    with pytest.raises(Conflict, match="checks-incomplete"):
        await start(cond, scene, failed.id, consent)
    with pytest.raises(Conflict, match="consents-missing"):
        await start(cond, scene, check, partial.id)

    later = await invited(
        app_db, make_hiring, org, starts_at=datetime.now(UTC) + timedelta(hours=1)
    )
    later_check, later_consent = await prepare(app_db, later)
    with pytest.raises(Conflict, match="interview-not-open"):
        await start(cond, later, later_check, later_consent)

    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE interviews SET expires_at = now() - interval '1 minute', "
                "starts_at = now() - interval '1 day' WHERE id = :id"
            ),
            {"id": scene.interview_id},
        )
    with pytest.raises(Gone, match="interview-expired"):
        await start(cond, scene, check, consent)


async def test_a_required_third_eye_blocks_the_start_unless_waived(
    app_db: Database,
    admin_engine: AsyncEngine,
    valkey: Redis,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    org = await make_organization("Acme")
    scene, waived = await invited(app_db, make_hiring, org), await invited(app_db, make_hiring, org)
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                'UPDATE interviews SET policy = policy || \'{"third_eye": "required"}\'::jsonb '
                "WHERE id IN (:a, :b)"
            ),
            {"a": scene.interview_id, "b": waived.interview_id},
        )
    cond = conductor(app_db, valkey)
    check, consent = await prepare(app_db, scene)
    with pytest.raises(Conflict, match="third-eye-required"):
        await start(cond, scene, check, consent)
    check, consent = await prepare(app_db, waived, accommodations=["third_eye_waiver"])
    assert (await start(cond, waived, check, consent)).view.third_eye == "optional"


async def test_an_interruption_pauses_and_resumes_under_the_policy(
    app_db: Database,
    admin_engine: AsyncEngine,
    valkey: Redis,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    scene = await invited(app_db, make_hiring, await make_organization("Acme"))
    await use_policy(admin_engine, scene, OLD_RESUME)  # assigned before C8-9
    check, consent = await prepare(app_db, scene, accommodations=["text_answers"])
    cond = conductor(app_db, valkey)
    started = await start(cond, scene, check, consent)
    deadline = started.view.deadline_at
    assert await cond.interrupt(
        scene.organization_id, scene.interview_id, reason="left", by=By.system()
    )
    assert not await cond.interrupt(
        scene.organization_id, scene.interview_id, reason="x", by=By.system()
    )
    view = await cond.session_state(scene.organization_id, scene.interview_id)
    assert view.status == "interrupted" and view.voice == "paused"
    # Ninety seconds away, then back: the deadline moves by the pause.
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE interview_sessions SET state = jsonb_set(state, '{clock,paused_since}', "
                "to_jsonb(now() - interval '90 seconds')) WHERE interview_id = :id"
            ),
            {"id": scene.interview_id},
        )
    resumed = await start(cond, scene, check, consent)
    assert resumed.resumed and resumed.view.status == "in_progress"
    assert resumed.view.message.startswith("Welcome back")
    moved = (resumed.view.deadline_at - deadline).total_seconds()
    assert 85 <= moved <= 100
    # Past the limit, resuming is refused, and the scheduler abandons it after the grace.
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE interview_sessions SET interruptions = 9 WHERE interview_id = :id"),
            {"id": scene.interview_id},
        )
    await cond.interrupt(scene.organization_id, scene.interview_id, reason="left", by=By.system())
    with pytest.raises(Conflict, match="resume-limit-reached"):
        await start(cond, scene, check, consent)
    report = await run_due(app_db, SETTINGS, now=datetime.now(UTC) + timedelta(minutes=6))
    assert report.abandoned == 1
    async with admin_engine.connect() as conn:
        abandoned = await conn.scalar(
            text(
                "SELECT count(*) FROM outbox_events WHERE topic = 'interview.abandoned' "
                "AND payload->>'interview_id' = :id"
            ),
            {"id": str(scene.interview_id)},
        )
    assert abandoned == 1  # so its transcript is still written
    async with app_db.tenant(scene.organization_id) as session:
        interview = await session.get_one(Interview, scene.interview_id)
        application = await session.get_one(Application, scene.application_id)
    assert interview.status == "abandoned" and application.stage == "shortlisted"


async def test_a_new_process_carries_on_from_the_checkpoint(
    app_db: Database, valkey: Redis, make_organization: MakeOrganization, make_hiring: Any
) -> None:
    scene = await invited(app_db, make_hiring, await make_organization("Acme"))
    check, consent = await prepare(app_db, scene, accommodations=["text_answers"])
    clock = Answering()
    first = conductor(app_db, valkey, clock=clock)
    view = (await start(first, scene, check, consent)).view
    view = (
        await first.answer(
            scene.organization_id,
            scene.interview_id,
            UUID(view.question.id),
            reply(view),
            mode="text",
            by=CANDIDATE,
        )
    ).view
    open_question = view.question.id
    # The process dies; another one picks the interview up from its checkpoint.
    second = conductor(app_db, valkey, clock=clock)
    restored = await second.session_state(scene.organization_id, scene.interview_id)
    assert restored.question.id == open_question
    with pytest.raises(Conflict, match="question-not-current"):
        await second.answer(
            scene.organization_id,
            scene.interview_id,
            UUID(int=1),
            STRONG,
            mode="text",
            by=CANDIDATE,
        )
    final = await finish_in_text(second, scene, restored, clock)
    assert final.status == "completed"
    async with app_db.tenant(scene.organization_id) as session:
        positions = (
            await session.scalars(
                select(InterviewQuestion.position)
                .where(InterviewQuestion.interview_id == scene.interview_id)
                .order_by(InterviewQuestion.position)
            )
        ).all()
    assert list(positions) == list(range(len(positions)))  # no turn lost or repeated


async def test_ending_early_from_an_interruption_still_completes_it(
    app_db: Database,
    admin_engine: AsyncEngine,
    valkey: Redis,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    scene = await invited(app_db, make_hiring, await make_organization("Acme"))
    check, consent = await prepare(app_db, scene, accommodations=["text_answers"])
    cond = conductor(app_db, valkey)
    await start(cond, scene, check, consent)
    await cond.interrupt(scene.organization_id, scene.interview_id, reason="left", by=By.system())
    status = await cond.complete(
        scene.organization_id, scene.interview_id, "candidate_ended", by=CANDIDATE
    )
    assert status == "completed"
    again = await cond.complete(scene.organization_id, scene.interview_id, "finished", by=CANDIDATE)
    assert again == "completed"
    async with admin_engine.connect() as conn:
        completed = await conn.scalar(
            text(
                "SELECT count(*) FROM outbox_events WHERE topic = 'interview.completed' "
                "AND payload->>'interview_id' = :id"
            ),
            {"id": str(scene.interview_id)},
        )
    assert completed == 1


async def test_workspace_snapshots_have_a_size_limit(
    app_db: Database, valkey: Redis, make_organization: MakeOrganization, make_hiring: Any
) -> None:
    scene = await invited(app_db, make_hiring, await make_organization("Acme"))
    check, consent = await prepare(app_db, scene, accommodations=["text_answers"])
    cond = conductor(app_db, valkey)
    view = (await start(cond, scene, check, consent)).view
    question = UUID(view.question.id)
    snapshot = await cond.workspace(
        scene.organization_id,
        scene.interview_id,
        question,
        kind="code",
        language="Python",
        content="print(1)",
    )
    assert snapshot.size == 8 and snapshot.language == "python"
    with pytest.raises(TooLarge, match="workspace-too-large"):
        await cond.workspace(
            scene.organization_id,
            scene.interview_id,
            question,
            kind="code",
            language=None,
            content="x" * 300_000,
        )


async def test_the_transcript_artifacts_are_written_and_recorded(
    app_db: Database, valkey: Redis, make_organization: MakeOrganization, make_hiring: Any
) -> None:
    scene = await invited(app_db, make_hiring, await make_organization("Acme"))
    check, consent = await prepare(app_db, scene, accommodations=["text_answers"])
    clock = Answering()
    cond = conductor(app_db, valkey, clock=clock)
    await finish_in_text(cond, scene, (await start(cond, scene, check, consent)).view, clock)
    blobs = Blobs()
    transcript = await write_artifacts(app_db, blobs, scene.organization_id, scene.interview_id)
    assert transcript.status == "ready" and set(transcript.artifacts) >= {"json", "vtt", "txt"}
    prefix = f"{scene.organization_id}/interviews/{scene.interview_id}/transcript/"
    assert sorted(blobs.files) == [
        prefix + n for n in ("transcript.json", "transcript.txt", "transcript.vtt")
    ]
    document = json.loads(blobs.files[prefix + "transcript.json"][0])
    assert document["summary"]["required_covered"] is True
    assert document["questions"][0]["kind"] == "introduction"
    vtt = blobs.files[prefix + "transcript.vtt"][0].decode()
    assert vtt.startswith("WEBVTT") and "<v AI>Hello" in vtt and "<v Candidate>" in vtt
    txt = blobs.files[prefix + "transcript.txt"][0].decode()
    assert "AI:\nHello" in txt and "Candidate:\n" in txt
    import hashlib

    data = blobs.files[prefix + "transcript.vtt"][0]
    assert transcript.artifacts["vtt"]["sha256"] == hashlib.sha256(data).hexdigest()


def test_vtt_cues_are_well_formed() -> None:
    row = TranscriptSegment(
        seq=1, speaker="ai", text="Hello --> there", start_ms=61_250, end_ms=63_000
    )
    assert render_vtt([row]).splitlines()[3:5] == [
        "00:01:01.250 --> 00:01:03.000",
        "<v AI>Hello -> there",
    ]


async def test_a_media_outage_at_the_first_start_commits_nothing(
    app_db: Database, valkey: Redis, make_organization: MakeOrganization, make_hiring: Any
) -> None:
    from hirevion_core.interview_session.conductor import MediaUnavailable

    scene = await invited(app_db, make_hiring, await make_organization("Acme"))
    check, consent = await prepare(app_db, scene)
    with pytest.raises(MediaUnavailable):
        await start(conductor(app_db, valkey, FakeMedia(fail=True)), scene, check, consent)
    async with app_db.tenant(scene.organization_id) as session:
        interview = await session.get_one(Interview, scene.interview_id)
        row = await session.get(InterviewSession, scene.interview_id)
    assert interview.status == "invited" and interview.started_at is None and row is None


async def test_a_departure_older_than_the_latest_connection_is_ignored(
    app_db: Database, valkey: Redis, make_organization: MakeOrganization, make_hiring: Any
) -> None:
    scene = await invited(app_db, make_hiring, await make_organization("Acme"))
    check, consent = await prepare(app_db, scene, accommodations=["text_answers"])
    cond = conductor(app_db, valkey)
    await start(cond, scene, check, consent)
    stale = datetime.now(UTC) - timedelta(seconds=30)
    assert not await cond.interrupt(
        scene.organization_id, scene.interview_id, reason="left", by=By.system(), observed_at=stale
    )
    assert await cond.interrupt(
        scene.organization_id,
        scene.interview_id,
        reason="left",
        by=By.system(),
        observed_at=datetime.now(UTC) + timedelta(seconds=1),
    )


async def test_new_events_only_start_from_the_newest_one(valkey: Redis) -> None:
    interview = UUID(int=42)
    assert await realtime.last_id(valkey, interview) == "0-0"
    first = await realtime.publish(valkey, interview, "AI_SPEAKING", {"text": "Hello"})
    assert await realtime.last_id(valkey, interview) == first
    second = await realtime.publish(valkey, interview, "QUESTION_STARTED", {"question_id": "q"})
    events = await realtime.read(valkey, interview, first)
    assert [e.id for e in events] == [second]


async def test_the_latest_draft_comes_back_and_a_follow_up_starts_from_its_parents(
    app_db: Database, valkey: Redis, make_organization: MakeOrganization, make_hiring: Any
) -> None:
    """ADR-0041: the notes pad restores its notes after a restart, and a follow-up of a design
    question starts from the notes typed for the question it follows."""
    scene = await invited(app_db, make_hiring, await make_organization("Acme"))
    check, consent = await prepare(app_db, scene, accommodations=["text_answers"])
    cond = conductor(app_db, valkey)
    view = (await start(cond, scene, check, consent)).view
    question = UUID(view.question.id)
    assert await cond.workspace_draft(scene.organization_id, scene.interview_id, question) is None
    for content in ("API -> cache", "API -> cache -> Postgres"):
        await cond.workspace(
            scene.organization_id,
            scene.interview_id,
            question,
            kind="whiteboard",
            language=None,
            content=content,
        )
    draft = await cond.workspace_draft(scene.organization_id, scene.interview_id, question)
    assert draft is not None and draft.content == "API -> cache -> Postgres"
    assert draft.kind == "whiteboard"

    follow_up = uuid7()
    async with app_db.tenant(scene.organization_id) as session:
        parent = await session.get_one(InterviewQuestion, question)
        session.add(
            InterviewQuestion(
                id=follow_up,
                organization_id=scene.organization_id,
                interview_id=scene.interview_id,
                parent_id=question,
                position=parent.position + 1,
                kind="follow_up",
                stage="follow_up",
                source="follow_up",
                text="And how would you keep the cache fresh?",
                asked_at=datetime.now(UTC),
                workspace="whiteboard",
            )
        )
    inherited = await cond.workspace_draft(scene.organization_id, scene.interview_id, follow_up)
    assert inherited is not None and inherited.content == "API -> cache -> Postgres"
    with pytest.raises(NotFound, match="question-not-found"):
        await cond.workspace_draft(scene.organization_id, scene.interview_id, uuid7())


async def test_an_interview_with_a_third_eye_also_gets_the_vision_agent(
    app_db: Database,
    admin_engine: AsyncEngine,
    valkey: Redis,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    """C7-1: the server watches the phone's picture during the interview, once per interview."""
    org = await make_organization("Acme")
    watched, plain = (
        await invited(app_db, make_hiring, org),
        await invited(app_db, make_hiring, org),
    )
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                'UPDATE interviews SET policy = policy || \'{"third_eye": "optional"}\'::jsonb '
                "WHERE id = :a"
            ),
            {"a": watched.interview_id},
        )
        await conn.execute(
            text(
                'UPDATE interviews SET policy = policy || \'{"third_eye": "off"}\'::jsonb '
                "WHERE id = :b"
            ),
            {"b": plain.interview_id},
        )
    media = FakeMedia()
    cond = conductor(app_db, valkey, media)
    check, consent = await prepare(app_db, watched)
    await start(cond, watched, check, consent)
    assert media.vision_dispatches == [f"iv-{watched.interview_id}"]
    # The app restarted while both agents run: no second vision agent.
    await valkey.set(f"hv:iv:{watched.interview_id}:agent", "job", ex=8)
    await valkey.set(f"hv:iv:{watched.interview_id}:vision", "job", ex=8)
    await start(cond, watched, check, consent)
    assert media.vision_dispatches == [f"iv-{watched.interview_id}"]
    # No third eye, nothing to watch.
    check, consent = await prepare(app_db, plain)
    await start(cond, plain, check, consent)
    assert media.vision_dispatches == [f"iv-{watched.interview_id}"]


async def test_a_vision_agent_that_left_a_running_interview_is_sent_again(
    app_db: Database,
    admin_engine: AsyncEngine,
    valkey: Redis,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    """C7-1: the vision agent crashed mid-interview; another one picks up the watch."""
    scene = await invited(app_db, make_hiring, await make_organization("Acme"))
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                'UPDATE interviews SET policy = policy || \'{"third_eye": "optional"}\'::jsonb '
                "WHERE id = :a"
            ),
            {"a": scene.interview_id},
        )
    media = FakeMedia()
    cond = conductor(app_db, valkey, media)
    check, consent = await prepare(app_db, scene)
    await start(cond, scene, check, consent)
    assert len(media.vision_dispatches) == 1
    assert await cond.redispatch_vision(scene.organization_id, scene.interview_id)
    assert len(media.vision_dispatches) == 2
    # One is running: nothing to do.
    await valkey.set(f"hv:iv:{scene.interview_id}:vision", "job", ex=8)
    assert not await cond.redispatch_vision(scene.organization_id, scene.interview_id)
    assert len(media.vision_dispatches) == 2


# One attempt (C8-9, product owner 2026-11-22): a new interview may be rejoined once, within
# 2 minutes, from the laptop that started it, with the clock running; then it ends as
# "left_early" and is evaluated.


async def _events(admin_engine: AsyncEngine, scene: Scene, action: str) -> list[Any]:
    async with admin_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT reason, to_status FROM interview_events WHERE interview_id = :id "
                "AND action = :action ORDER BY created_at"
            ),
            {"id": scene.interview_id, "action": action},
        )
        return list(rows.all())


async def _outbox(admin_engine: AsyncEngine, scene: Scene, topic: str) -> int:
    async with admin_engine.connect() as conn:
        count = await conn.scalar(
            text(
                "SELECT count(*) FROM outbox_events WHERE topic = :topic "
                "AND payload->>'interview_id' = :id"
            ),
            {"topic": topic, "id": str(scene.interview_id)},
        )
    return int(count or 0)


async def test_the_laptop_that_started_is_the_only_one_that_may_rejoin(
    app_db: Database, valkey: Redis, make_organization: MakeOrganization, make_hiring: Any
) -> None:
    scene = await invited(app_db, make_hiring, await make_organization("Acme"))
    check, consent = await prepare(app_db, scene, accommodations=["text_answers"])
    cond = conductor(app_db, valkey)
    started = await start(cond, scene, check, consent)
    async with app_db.tenant(scene.organization_id) as session:
        row = await session.get_one(InterviewSession, scene.interview_id)
    assert row.device_jkt == LAPTOP
    assert await cond.interrupt(
        scene.organization_id, scene.interview_id, reason="left", by=By.system()
    )
    with pytest.raises(Conflict, match="interview-other-device"):
        await start(cond, scene, check, consent, device="another-laptop")
    # The same laptop rejoins without redoing the checks; the clock never stopped.
    resumed = await start(cond, scene, None, None)
    assert resumed.resumed and resumed.view.status == "in_progress"
    assert resumed.view.deadline_at == started.view.deadline_at


async def test_a_second_drop_ends_the_interview_and_it_is_evaluated(
    app_db: Database,
    admin_engine: AsyncEngine,
    valkey: Redis,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    scene = await invited(app_db, make_hiring, await make_organization("Acme"))
    check, consent = await prepare(app_db, scene, accommodations=["text_answers"])
    cond = conductor(app_db, valkey)
    await start(cond, scene, check, consent)
    await cond.interrupt(scene.organization_id, scene.interview_id, reason="left", by=By.system())
    await start(cond, scene, None, None)
    assert await cond.interrupt(
        scene.organization_id, scene.interview_id, reason="left", by=By.system()
    )
    async with app_db.tenant(scene.organization_id) as session:
        interview = await session.get_one(Interview, scene.interview_id)
        application = await session.get_one(Application, scene.application_id)
    assert interview.status == "completed"
    assert application.stage == "interviewed"
    assert await _events(admin_engine, scene, "completed") == [("left_early", "completed")]
    # Both drops are in the history, the second one without a pause.
    assert [reason for reason, _ in await _events(admin_engine, scene, "interrupted")] == [
        "left",
        "left",
    ]
    assert await _outbox(admin_engine, scene, "evaluation") == 1
    with pytest.raises(Conflict, match="interview-already-taken"):
        await start(cond, scene, None, None)


async def test_a_repeated_start_is_answered_again_without_using_the_reconnect(
    app_db: Database,
    admin_engine: AsyncEngine,
    valkey: Redis,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    scene = await invited(app_db, make_hiring, await make_organization("Acme"))
    check, consent = await prepare(app_db, scene, accommodations=["text_answers"])
    media = FakeMedia()
    cond = conductor(app_db, valkey, media)
    await start(cond, scene, check, consent)
    async with app_db.tenant(scene.organization_id) as session:
        interview = await session.get_one(Interview, scene.interview_id)
    identity = candidate_identity(interview.candidate_id)
    media.present.add(identity)
    with pytest.raises(Conflict, match="interview-in-use"):
        await start(cond, scene, None, None)  # a second app while the first is still in
    media.present.discard(identity)
    # The start's answer was lost: asking again (twice) is answered, and costs nothing.
    for _ in range(2):
        again = await start(cond, scene, None, None)
        assert again.view.status == "in_progress"
    async with app_db.tenant(scene.organization_id) as session:
        row = await session.get_one(InterviewSession, scene.interview_id)
    assert row.interruptions == 0
    assert await _events(admin_engine, scene, "completed") == []


async def test_the_scheduler_ends_a_strict_interview_after_the_window(
    app_db: Database,
    admin_engine: AsyncEngine,
    valkey: Redis,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    scene = await invited(app_db, make_hiring, await make_organization("Acme"))
    check, consent = await prepare(app_db, scene)
    cond = conductor(app_db, valkey)
    await start(cond, scene, check, consent)
    await cond.interrupt(scene.organization_id, scene.interview_id, reason="left", by=By.system())
    with pytest.raises(Conflict, match="interview-other-device"):
        await start(cond, scene, None, None, device=None)
    report = await run_due(app_db, SETTINGS, now=datetime.now(UTC) + timedelta(minutes=3))
    assert report.ended_early >= 1  # other tests may leave interrupted interviews too
    async with app_db.tenant(scene.organization_id) as session:
        interview = await session.get_one(Interview, scene.interview_id)
        application = await session.get_one(Application, scene.application_id)
        row = await session.get_one(InterviewSession, scene.interview_id)
    assert interview.status == "completed" and application.stage == "interviewed"
    assert row.state["ended_reason"] == "left_early" and row.ended_at is not None
    async with app_db.tenant(scene.organization_id) as session:
        still_open = await session.scalar(
            select(InterviewQuestion.id).where(
                InterviewQuestion.interview_id == scene.interview_id,
                InterviewQuestion.status == "asked",
            )
        )
    assert still_open is None  # the question open at the drop was closed
    assert await _events(admin_engine, scene, "completed") == [("left_early", "completed")]
    assert await _outbox(admin_engine, scene, "evaluation") == 1
    assert await _outbox(admin_engine, scene, "interview.completed") == 1


# Prepared questions (C8-10, owner 2026-11-22): written when the interview is created, distinct,
# at every level; the interview's pool comes from them, and a newer version merges in.


async def test_a_new_interview_asks_for_its_prepared_questions(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    scene = await invited(app_db, make_hiring, await make_organization("Acme"))
    async with admin_engine.connect() as conn:
        queued = await conn.scalar(
            text(
                "SELECT count(*) FROM outbox_events WHERE topic = 'interview.plan' "
                "AND payload->>'interview_id' = :id AND payload->>'action' = 'plan'"
            ),
            {"id": str(scene.interview_id)},
        )
    assert queued == 1


async def test_the_worker_prepares_distinct_questions_at_every_level(
    app_db: Database,
    valkey: Redis,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    scene = await invited(app_db, make_hiring, await make_organization("Acme"))
    ai = build_ai(AiSettings(profile="mock"), app_db)
    async with app_db.tenant(scene.organization_id) as session:
        interview = await session.get_one(Interview, scene.interview_id)
        plan = await write_plan(session, ai, interview)
        items = list(plan.items)
        assert plan.status == "ready" and plan.version == 1
        again = await write_plan(session, ai, interview)  # a duplicate event changes nothing
        assert again.version == 1
    assert len({said(i["text"]) for i in items}) == len(items)
    concepts = [i["concept"] for i in items if i["concept"]]
    assert len(set(concepts)) == len(concepts)
    required = {i["skill"] for i in items}
    for skill in required:
        assert {i["difficulty"] for i in items if i["skill"] == skill} == {"easy", "medium", "hard"}
    # The interview's pool now comes from the plan.
    check, consent = await prepare(app_db, scene)
    cond = conductor(app_db, valkey)
    await start(cond, scene, check, consent)
    async with app_db.tenant(scene.organization_id) as session:
        row = await session.get_one(InterviewSession, scene.interview_id)
    assert row.state["plan_version"] == 1
    assert {q["key"] for q in row.state["pool"]} >= {i["key"] for i in items}

    # A top-up adds new questions on new concepts, and the running interview merges them.
    async with app_db.tenant(scene.organization_id) as session:
        interview = await session.get_one(Interview, scene.interview_id)
        topped = await write_plan(session, ai, interview, top_up=True)
        assert topped.version == 2 and len(topped.items) > len(items)
        added = topped.items[len(items) :]
    assert not {said(i["text"]) for i in added} & {said(i["text"]) for i in items}
    view = await cond.session_state(scene.organization_id, scene.interview_id)
    assert view.status == "in_progress"
    _, _, state = await cond._checkpoint(scene.organization_id, scene.interview_id)
    assert state.plan_version == 2
    assert {i["key"] for i in added} <= {q.key for q in state.pool}
