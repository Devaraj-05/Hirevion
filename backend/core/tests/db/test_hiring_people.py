"""What people add to a candidate's file (SP-17; ADR-0023): the Hiring Manager's input, notes, and
changes to the AI's scores. Each is kept as a new row and audited; the evaluation is untouched."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.access.actor import Actor
from hirevion_core.access.errors import Conflict, Invalid, NotFound
from hirevion_core.ai import build_ai
from hirevion_core.ai.settings import AiSettings
from hirevion_core.db.session import Database
from hirevion_core.evaluation.service import evaluate_interview
from hirevion_core.hiring import inputs, notes, scores
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.models import Application, Interview

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]


def actor(org: UUID, user: UUID, *roles: str) -> Actor:
    return Actor(user, org, frozenset(permissions_for(roles)))


async def audited(admin_engine: AsyncEngine, org: UUID, action: str) -> list[dict[str, Any]]:
    async with admin_engine.begin() as conn:
        rows = await conn.execute(
            text(
                "SELECT details FROM audit_logs WHERE organization_id = :o AND action = :a "
                "ORDER BY seq"
            ),
            {"o": org, "a": action},
        )
        return [dict(r.details) for r in rows]


async def evaluated(app_db: Database, scene: Any) -> None:
    ai = build_ai(AiSettings(profile="mock"), app_db)  # type: ignore[call-arg]
    await evaluate_interview(app_db, ai.llm, scene.organization_id, scene.interview_id)


async def test_a_hiring_manager_recommends_with_a_rationale_and_the_latest_counts(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring: Any,
    make_user: Any,
) -> None:
    org = await make_organization("Acme")
    hiring = await make_hiring(org)
    manager = await make_user(org, roles=["hiring_manager"])
    other = await make_user(org, roles=["hiring_manager"], name="Other Manager")
    async with app_db.tenant(org) as session:
        application = await session.get_one(Application, hiring.application_id)
        first = await inputs.add_input(
            session,
            actor(org, manager, "hiring_manager"),
            application,
            recommendation="hire",
            ratings={"technical": 4, "communication": 5},
            rationale="Clear thinker; the team needs PostgreSQL depth.",
        )
        assert first.recommendation == "hire" and first.ratings == {
            "technical": 4,
            "communication": 5,
        }
        await inputs.add_input(
            session,
            actor(org, manager, "hiring_manager"),
            application,
            recommendation="strong_hire",
            ratings={},
            rationale="Spoke with the candidate again.",
        )
        await inputs.add_input(
            session,
            actor(org, other, "hiring_manager"),
            application,
            recommendation="hold",
            ratings={},
            rationale="Want to see the coding round first.",
        )
        current = await inputs.current_inputs(session, application.id)
        history = await inputs.all_inputs(session, application.id)
    assert {row.author_id: row.recommendation for row in current} == {
        manager: "strong_hire",
        other: "hold",
    }
    assert len(history) == 3
    assert application.hiring_status == "under_review"  # input never moves the status
    assert len(await audited(admin_engine, org, "hiring.input_added")) == 3


async def test_hiring_input_is_checked(
    app_db: Database,
    make_organization: MakeOrganization,
    make_hiring: Any,
    make_user: Any,
) -> None:
    org = await make_organization("Acme")
    hiring = await make_hiring(org)
    manager = await make_user(org, roles=["hiring_manager"])
    me = actor(org, manager, "hiring_manager")
    async with app_db.tenant(org) as session:
        application = await session.get_one(Application, hiring.application_id)
        for bad in (
            {"recommendation": "maybe", "ratings": {}, "rationale": "x"},
            {"recommendation": "hire", "ratings": {}, "rationale": "   "},
            {"recommendation": "hire", "ratings": {"charm": 3}, "rationale": "x"},
            {"recommendation": "hire", "ratings": {"technical": 6}, "rationale": "x"},
            {"recommendation": "hire", "ratings": {}, "rationale": "x" * 4001},
        ):
            with pytest.raises(Invalid):
                await inputs.add_input(session, me, application, **bad)


async def test_notes_belong_to_a_candidate_and_optionally_to_a_moment_of_an_interview(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_completed_interview: Any,
) -> None:
    org = await make_organization("Acme")
    scene = await make_completed_interview(org)
    recruiter = actor(org, scene.hiring.recruiter_id, "recruiter")
    async with app_db.tenant(org) as session:
        interview = await session.get_one(Interview, scene.interview_id)
        general = await notes.add_note(
            session, recruiter, candidate_id=scene.hiring.candidate_id, body="Referred by Priya."
        )
        timed = await notes.add_note(
            session,
            recruiter,
            candidate_id=scene.hiring.candidate_id,
            interview=interview,
            body="Hesitated on indexes here.",
            at_ms=61_000,
        )
        assert general.interview_id is None and timed.at_ms == 61_000
        assert timed.application_id == scene.hiring.application_id
        everything = await notes.list_notes(session, scene.hiring.candidate_id)
        mine = await notes.list_notes(session, scene.hiring.candidate_id, interview_id=interview.id)
        with pytest.raises(Invalid):
            await notes.add_note(
                session, recruiter, candidate_id=scene.hiring.candidate_id, body="   "
            )
        with pytest.raises(Invalid):
            await notes.add_note(
                session, recruiter, candidate_id=scene.hiring.candidate_id, body="x" * 4001
            )
        with pytest.raises(Invalid):
            await notes.add_note(
                session,
                recruiter,
                candidate_id=scene.hiring.candidate_id,
                interview=interview,
                body="Negative moment",
                at_ms=-5,
            )
    assert [n.body for n in everything] == ["Hesitated on indexes here.", "Referred by Priya."]
    assert [n.body for n in mine] == ["Hesitated on indexes here."]
    assert len(await audited(admin_engine, org, "candidate.note_added")) == 2


async def test_a_score_change_keeps_the_ai_score_and_says_why(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_completed_interview: Any,
) -> None:
    org = await make_organization("Acme")
    scene = await make_completed_interview(org)
    recruiter = actor(org, scene.hiring.recruiter_id, "recruiter")
    async with app_db.tenant(org) as session:
        interview = await session.get_one(Interview, scene.interview_id)
        with pytest.raises(Conflict) as early:  # nothing to change before the evaluation
            await scores.change_score(
                session, recruiter, interview, "overall", None, 7, "Reviewed the recording"
            )
        assert early.value.code == "not-evaluated"
    await evaluated(app_db, scene)
    async with app_db.tenant(org) as session:
        interview = await session.get_one(Interview, scene.interview_id)
        before = await scores.score_view(session, interview)
        ai_overall = before.overall.ai
        assert ai_overall is not None and before.overall.value == ai_overall
        change = await scores.change_score(
            session, recruiter, interview, "overall", None, 8.5, "Second reviewer: stronger depth"
        )
        assert float(change.previous_score) == pytest.approx(ai_overall)
        assert float(change.new_score) == 8.5
        again = await scores.change_score(
            session, recruiter, interview, "overall", None, 9, "Raised again after the call"
        )
        assert float(again.previous_score) == 8.5  # the previous value is what it was, not the AI's
        after = await scores.score_view(session, interview)
    assert after.overall.ai == ai_overall and after.overall.value == 9.0
    assert after.overall.change is not None and after.overall.change.reason.startswith("Raised")
    entries = await audited(admin_engine, org, "score.modified")
    assert [e["new"] for e in entries] == [8.5, 9.0]
    assert entries[0]["scope"] == "overall" and entries[0]["reason"].startswith("Second")
    # The evaluation itself is as the AI left it.
    async with admin_engine.begin() as conn:
        stored = await conn.scalar(
            text("SELECT overall_score FROM evaluations WHERE interview_id = :i"),
            {"i": scene.interview_id},
        )
    assert float(stored) == pytest.approx(ai_overall, abs=0.01)


async def test_skills_and_questions_are_changed_by_name_and_id_and_checked(
    app_db: Database,
    make_organization: MakeOrganization,
    make_completed_interview: Any,
) -> None:
    org = await make_organization("Acme")
    scene = await make_completed_interview(org)
    await evaluated(app_db, scene)
    recruiter = actor(org, scene.hiring.recruiter_id, "recruiter")
    async with app_db.tenant(org) as session:
        interview = await session.get_one(Interview, scene.interview_id)
        await scores.change_score(session, recruiter, interview, "skill", "Python", 4, "Weak")
        await scores.change_score(
            session,
            recruiter,
            interview,
            "question",
            str(scene.questions["postgres"]),
            9,
            "Excellent",
        )
        await scores.change_score(
            session, recruiter, interview, "communication", None, 6.5, "Clear but slow"
        )
        view = await scores.score_view(session, interview)
        assert view.skills["Python"].value == 4.0 and view.skills["Python"].ai is not None
        assert view.skills["PostgreSQL"].change is None
        assert view.questions[str(scene.questions["postgres"])].value == 9.0
        assert view.communication.value == 6.5
        for args, code in (
            (("skill", "Rust", 5, "x"), "unknown-target"),
            (("question", str(scene.questions["intro"]), 5, "x"), "unknown-target"),
            (("skill", None, 5, "x"), "unknown-target"),
            (("overall", "Python", 5, "x"), "unknown-target"),
            (("overall", None, 11, "x"), "invalid-score"),
            (("overall", None, -1, "x"), "invalid-score"),
            (("overall", None, 5, "  "), "reason-required"),
            (("galaxy", None, 5, "x"), "invalid-scope"),
        ):
            with pytest.raises((Invalid, NotFound)) as error:
                await scores.change_score(session, recruiter, interview, *args)
            assert error.value.code == code, args
        with pytest.raises(Conflict) as same:  # a change must change something
            await scores.change_score(
                session, recruiter, interview, "communication", None, 6.5, "x"
            )
        assert same.value.code == "no-change"
