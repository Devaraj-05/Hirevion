"""Human calibration (SP-10 Task 5): reviewers record their own scores, and the organisation's
agreement with the AI is measured."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select

from hirevion_core.access.actor import Actor
from hirevion_core.access.errors import Conflict, Invalid
from hirevion_core.ai import AiServices, build_ai
from hirevion_core.ai.settings import AiSettings
from hirevion_core.db.session import Database
from hirevion_core.evaluation.calibration import agreement, own_scores, record_human_scores
from hirevion_core.evaluation.service import evaluate_interview
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.models import Interview, QuestionEvaluation

pytestmark = pytest.mark.db


def mock_ai(app_db: Database) -> AiServices:
    return build_ai(AiSettings(profile="mock"), app_db)  # type: ignore[call-arg]


def actor(scene: Any, user_id: UUID, role: str = "recruiter") -> Actor:
    return Actor(user_id, scene.organization_id, frozenset(permissions_for([role])))


async def record(
    app_db: Database, scene: Any, who: Actor, key: str, scores: dict[str, float], note: str = ""
) -> Any:
    async with app_db.tenant(scene.organization_id) as session:
        interview = await session.get_one(Interview, scene.interview_id)
        return await record_human_scores(
            session, who, interview, scene.questions[key], scores, note
        )


async def test_a_reviewer_records_and_changes_their_own_scores(
    app_db: Database, make_organization: Any, make_completed_interview: Any
) -> None:
    scene = await make_completed_interview(await make_organization("Acme"))
    me = actor(scene, scene.hiring.recruiter_id)
    first = await record(app_db, scene, me, "postgres", {"correctness": 8, "clarity": 6.5}, "ok")
    assert first.dimensions == {"correctness": 8.0, "clarity": 6.5} and first.note == "ok"
    again = await record(app_db, scene, me, "postgres", {"correctness": 9}, "better")
    assert again.id == first.id and again.dimensions == {"correctness": 9.0}
    async with app_db.tenant(scene.organization_id) as session:
        mine = await own_scores(session, scene.interview_id, me.user_id)
    assert [(r.question_id, r.note) for r in mine] == [(scene.questions["postgres"], "better")]


@pytest.mark.parametrize(
    "scores",
    [{}, {"charisma": 5}, {"clarity": 11}, {"clarity": -1}, {"clarity": "high"}, {"clarity": True}],
)
async def test_scores_must_be_known_dimensions_between_zero_and_ten(
    app_db: Database, make_organization: Any, make_completed_interview: Any, scores: Any
) -> None:
    scene = await make_completed_interview(await make_organization("Acme"))
    with pytest.raises(Invalid):
        await record(app_db, scene, actor(scene, scene.hiring.recruiter_id), "postgres", scores)


async def test_only_scored_questions_of_a_finished_interview_can_be_scored(
    app_db: Database, make_organization: Any, make_completed_interview: Any
) -> None:
    scene = await make_completed_interview(await make_organization("Acme"))
    me = actor(scene, scene.hiring.recruiter_id)
    with pytest.raises(Invalid, match="question-not-scored"):
        await record(app_db, scene, me, "intro", {"clarity": 5})
    live = await make_completed_interview(await make_organization("Globex"), status="in_progress")
    with pytest.raises(Conflict):
        await record(
            app_db, live, actor(live, live.hiring.recruiter_id), "postgres", {"clarity": 5}
        )


async def test_agreement_compares_each_reviewers_scores_with_the_evaluations(
    app_db: Database,
    make_organization: Any,
    make_completed_interview: Any,
    make_user: Any,
) -> None:
    scene = await make_completed_interview(await make_organization("Acme"))
    async with app_db.tenant(scene.organization_id) as session:
        assert (await agreement(session))["pairs"] == 0  # nothing to compare yet
    await evaluate_interview(app_db, mock_ai(app_db).llm, scene.organization_id, scene.interview_id)
    async with app_db.tenant(scene.organization_id) as session:
        rows = (
            await session.scalars(
                select(QuestionEvaluation).where(
                    QuestionEvaluation.question_id == scene.questions["postgres"]
                )
            )
        ).all()
    ai = {name: d["score"] for name, d in rows[0].dimensions.items()}
    me = actor(scene, scene.hiring.recruiter_id)
    other = await make_user(scene.organization_id, roles=["interviewer"])
    await record(
        app_db,
        scene,
        me,
        "postgres",
        {"correctness": ai["correctness"], "clarity": ai["clarity"] + 1},
    )
    await record(
        app_db,
        scene,
        actor(scene, other, "interviewer"),
        "postgres",
        {"correctness": ai["correctness"] - 2},
    )
    async with app_db.tenant(scene.organization_id) as session:
        stats = await agreement(session)
    assert stats["pairs"] == 3 and stats["reviewers"] == 2 and stats["questions"] == 1
    assert stats["overall"]["n"] == 3
    assert stats["overall"]["mean_abs_diff"] == pytest.approx((0 + 1 + 2) / 3, abs=0.01)
    assert stats["overall"]["within_one"] == pytest.approx(2 / 3, abs=0.01)
    assert set(stats["by_dimension"]) == {"correctness", "clarity"}
    assert stats["by_dimension"]["correctness"]["n"] == 2
    # The AI scored (clarity - 1) and (correctness + 2) against these two humans.
    assert stats["bias"] == pytest.approx((0 - 1 + 2) / 3, abs=0.01)


async def test_other_organisations_see_nothing(
    app_db: Database, make_organization: Any, make_completed_interview: Any
) -> None:
    scene = await make_completed_interview(await make_organization("Acme"))
    await evaluate_interview(app_db, mock_ai(app_db).llm, scene.organization_id, scene.interview_id)
    await record(app_db, scene, actor(scene, scene.hiring.recruiter_id), "postgres", {"clarity": 5})
    other = await make_organization("Globex")
    async with app_db.tenant(other) as session:
        assert (await agreement(session))["pairs"] == 0
