"""The evaluation over HTTP (SP-10 Task 8): reading an interview's evaluation with its evidence,
scoped to the people who may see the interview; reviewers' own scores and the organisation's
agreement; and the admin's retry and pinned re-run."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.ai import AiServices, build_ai
from hirevion_core.ai.settings import AiSettings
from hirevion_core.db.session import Database
from hirevion_core.evaluation.registry import DIMENSIONS
from hirevion_core.evaluation.runner import handle_evaluation_event
from hirevion_core.evaluation.service import evaluate_interview

pytestmark = pytest.mark.db


def mock_ai(app_db: Database) -> AiServices:
    return build_ai(AiSettings(profile="mock"), app_db)  # type: ignore[call-arg]


async def evaluated(app_db: Database, scene: Any) -> None:
    await evaluate_interview(app_db, mock_ai(app_db).llm, scene.organization_id, scene.interview_id)


def url(scene: Any, tail: str = "") -> str:
    return f"/api/v1/interviews/{scene.interview_id}{tail}"


async def test_before_the_interview_is_evaluated_there_is_nothing_to_read(
    signed_in: Any, make_organization: Any, make_completed_interview: Any
) -> None:
    scene = await make_completed_interview(await make_organization("Acme"))
    client = await signed_in(scene.organization_id, scene.hiring.recruiter_id)
    body = (await client.get(url(scene, "/evaluation"))).json()
    assert body["state"] == "none" and body["evaluation"] is None
    assert body["interview_status"] == "completed"
    missing = await client.get(url(scene, f"/evaluation/questions/{scene.questions['postgres']}"))
    assert missing.status_code == 404 and missing.json()["code"] == "evaluation-not-found"


async def test_the_evaluation_has_scores_evidence_and_versions(
    app_db: Database, signed_in: Any, make_organization: Any, make_completed_interview: Any
) -> None:
    scene = await make_completed_interview(await make_organization("Acme"))
    await evaluated(app_db, scene)
    client = await signed_in(scene.organization_id, scene.hiring.recruiter_id)

    response = await client.get(url(scene, "/evaluation"))
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "ready" and data["interview_status"] == "evaluated"
    body = data["evaluation"]
    assert body["versions"]["evaluation"] == "evaluation-v1"
    assert body["versions"]["prompt"] == "evaluation-question-v1"
    assert body["versions"]["rubric"].startswith("dimensions-v1+w")
    assert body["versions"]["model"] == "mock-llm" and sum(body["rubric_weights"].values()) == 100
    assert body["overall_score"] is not None and body["coding"]["status"] == "pending"
    assert {s["skill"] for s in body["skills"]} == {"PostgreSQL", "Python"}
    postgres = next(s for s in body["skills"] if s["skill"] == "PostgreSQL")
    assert postgres["supported"] and postgres["evidence"][0]["quote"]
    assert body["communication"]["score"] is not None
    assert body["strengths"] and all(f["supported"] and f["evidence"] for f in body["strengths"])
    assert body["knowledge_gaps"]
    assert [q["position"] for q in body["questions"]] == [2, 3, 4]
    assert body["follow_up_performance"]["asked"] == 1

    detail = await client.get(url(scene, f"/evaluation/questions/{scene.questions['postgres']}"))
    assert detail.status_code == 200
    question = detail.json()
    assert [d["dimension"] for d in question["dimensions"]] == list(DIMENSIONS)
    for dimension in question["dimensions"]:
        assert dimension["supported"] and dimension["weight"] > 0
        assert dimension["evidence"][0]["start_ms"] >= 0 and dimension["evidence"][0]["seq"] > 0
    assert question["model"] == "mock-llm" and question["text"].startswith("How do you find")


async def test_only_people_who_may_see_the_interview_can_read_its_evaluation(
    app_db: Database,
    admin_engine: AsyncEngine,
    signed_in: Any,
    make_organization: Any,
    make_user: Any,
    make_completed_interview: Any,
) -> None:
    org = await make_organization("Acme")
    scene = await make_completed_interview(org)
    await evaluated(app_db, scene)
    reviewer = await make_user(org, roles=["interviewer"])
    client = await signed_in(org, reviewer)
    assert (await client.get(url(scene, "/evaluation"))).status_code == 404  # not theirs
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO interview_reviewers (organization_id, interview_id, user_id) "
                "VALUES (:org, :iv, :user)"
            ),
            {"org": org, "iv": scene.interview_id, "user": reviewer},
        )
    assert (await client.get(url(scene, "/evaluation"))).status_code == 200
    stranger = await make_user(await make_organization("Globex"), roles=["recruiter"])
    outsider = await signed_in((await _organization_of(admin_engine, stranger)), stranger)
    assert (await outsider.get(url(scene, "/evaluation"))).status_code == 404


async def _organization_of(engine: AsyncEngine, user_id: UUID) -> UUID:
    async with engine.begin() as conn:
        value = await conn.scalar(
            text("SELECT organization_id FROM users WHERE id = :id"), {"id": user_id}
        )
    return UUID(str(value))


async def test_reviewers_score_for_themselves_and_the_organisations_agreement_follows(
    app_db: Database,
    signed_in: Any,
    make_organization: Any,
    make_user: Any,
    make_completed_interview: Any,
) -> None:
    org = await make_organization("Acme")
    scene = await make_completed_interview(org)
    await evaluated(app_db, scene)
    client = await signed_in(org, scene.hiring.recruiter_id)
    question = scene.questions["postgres"]
    path = url(scene, f"/questions/{question}/human-scores")

    saved = await client.put(
        path, json={"dimensions": {"correctness": 8, "clarity": 6.5}, "note": "ok"}
    )
    assert saved.status_code == 200
    assert saved.json()["dimensions"] == {"correctness": 8.0, "clarity": 6.5}
    await client.put(path, json={"dimensions": {"correctness": 9}})
    mine = (await client.get(url(scene, "/human-scores"))).json()
    assert [(m["question_id"], m["dimensions"]) for m in mine] == [
        (str(question), {"correctness": 9.0})
    ]

    unknown = await client.put(path, json={"dimensions": {"charisma": 5}})
    assert unknown.status_code == 422 and unknown.json()["code"] == "unknown-dimension"
    too_high = await client.put(path, json={"dimensions": {"clarity": 11}})
    assert too_high.status_code == 422 and too_high.json()["code"] == "invalid-score"
    not_scored = await client.put(
        url(scene, f"/questions/{scene.questions['intro']}/human-scores"),
        json={"dimensions": {"clarity": 5}},
    )
    assert not_scored.status_code == 422 and not_scored.json()["code"] == "question-not-scored"

    other = await signed_in(org, await make_user(org, roles=["org_admin"]))
    assert (await other.get(url(scene, "/human-scores"))).json() == []  # blind to others

    stats = (await client.get("/api/v1/evaluation/calibration")).json()
    assert stats["pairs"] == 1 and stats["reviewers"] == 1 and stats["questions"] == 1
    assert stats["overall"]["n"] == 1 and set(stats["by_dimension"]) == {"correctness"}
    assert stats["bias"] is not None


async def test_calibration_statistics_are_for_roles_that_see_analytics(
    signed_in: Any, make_organization: Any, make_user: Any
) -> None:
    org = await make_organization("Acme")
    interviewer = await signed_in(org, await make_user(org, roles=["interviewer"]))
    assert (await interviewer.get("/api/v1/evaluation/calibration")).status_code == 403
    empty = await signed_in(org, await make_user(org, roles=["recruiter"]))
    assert (await empty.get("/api/v1/evaluation/calibration")).json()["pairs"] == 0


async def test_an_admin_queues_a_pinned_rerun_and_reads_how_far_it_moved(
    app_db: Database,
    admin_engine: AsyncEngine,
    signed_in: Any,
    make_organization: Any,
    make_user: Any,
    make_completed_interview: Any,
) -> None:
    org = await make_organization("Acme")
    scene = await make_completed_interview(org)
    await evaluated(app_db, scene)
    admin = await make_user(org, roles=["org_admin"])
    client = await signed_in(org, admin)
    recruiter = await signed_in(org, scene.hiring.recruiter_id)
    assert (await recruiter.post(url(scene, "/evaluation/rerun"))).status_code == 403
    async with admin_engine.begin() as conn:
        await conn.execute(text("DELETE FROM outbox_events"))

    queued = await client.post(url(scene, "/evaluation/rerun"))
    assert queued.status_code == 202 and queued.json() == {"action": "rerun"}
    async with admin_engine.begin() as conn:
        [event] = (
            await conn.execute(text("SELECT payload FROM outbox_events WHERE topic = 'evaluation'"))
        ).all()
    assert event[0]["action"] == "rerun" and event[0]["requested_by"] == str(admin)

    assert (await client.get(url(scene, "/evaluation/reruns"))).json() == []
    await handle_evaluation_event(app_db, mock_ai(app_db), org, event[0])
    [rerun] = (await client.get(url(scene, "/evaluation/reruns"))).json()
    assert rerun["status"] == "ready" and rerun["within_tolerance"] is True
    assert rerun["requested_by"] == str(admin) and rerun["diff"]["max_dimension_diff"] == 0
    assert rerun["prompt_version"] == "evaluation-question-v1"
    # The interview's own evaluation is the one it had.
    assert (await client.get(url(scene, "/evaluation"))).json()["evaluation"]["sequence"] == 1


async def test_an_evaluation_that_never_finished_can_be_retried_and_others_cannot(
    signed_in: Any, make_organization: Any, make_user: Any, make_completed_interview: Any
) -> None:
    org = await make_organization("Acme")
    admin = await signed_in(org, await make_user(org, roles=["org_admin"]))
    scene = await make_completed_interview(org)
    queued = await admin.post(url(scene, "/evaluation/rerun"))
    assert queued.status_code == 202 and queued.json() == {"action": "evaluate"}
    gone = await make_completed_interview(org, status="abandoned")
    refused = await admin.post(url(gone, "/evaluation/rerun"))
    assert refused.status_code == 409 and refused.json()["code"] == "not-evaluable"


async def test_a_rerun_that_cannot_be_reproduced_is_refused_with_its_reason(
    app_db: Database,
    admin_engine: AsyncEngine,
    signed_in: Any,
    make_organization: Any,
    make_user: Any,
    make_completed_interview: Any,
) -> None:
    org = await make_organization("Acme")
    scene = await make_completed_interview(org)
    await evaluated(app_db, scene)
    async with admin_engine.begin() as conn:
        await conn.execute(text("UPDATE evaluations SET evaluation_version = 'evaluation-v0'"))
        await conn.execute(text("DELETE FROM outbox_events"))
    admin = await signed_in(org, await make_user(org, roles=["org_admin"]))
    refused = await admin.post(url(scene, "/evaluation/rerun"))
    assert refused.status_code == 409
    assert refused.json()["code"] == "evaluation-not-reproducible"
    assert "evaluation-v0" in refused.json()["detail"]
    async with admin_engine.begin() as conn:
        queued = await conn.scalar(
            text("SELECT count(*) FROM outbox_events WHERE topic = 'evaluation'")
        )
    assert queued == 0
