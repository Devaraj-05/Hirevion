"""Evaluation runs that overlap, stall or half-fail (SP-10 review): a duplicate event never
touches a live run, a run keeps itself alive, a failed model call leaves an evaluation that can be
redone, the questions run concurrently within a bound, and a re-run that can never work is
recorded once instead of being retried."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.ai import AiServices, build_ai
from hirevion_core.ai.settings import AiSettings
from hirevion_core.ai.types import AiOutputInvalid
from hirevion_core.db.session import Database
from hirevion_core.evaluation import service
from hirevion_core.evaluation.aggregate import EMPTY, Synthesis
from hirevion_core.evaluation.runner import give_up_evaluation, handle_evaluation_event
from hirevion_core.evaluation.service import (
    EvaluationBusy,
    EvaluationLost,
    Unreproducible,
    check_reproducible,
    evaluate_interview,
)
from hirevion_core.models import Evaluation, Interview, QuestionEvaluation

pytestmark = pytest.mark.db


def mock_ai(app_db: Database) -> AiServices:
    return build_ai(AiSettings(profile="mock"), app_db)  # type: ignore[call-arg]


class Spy:
    """An LLM that delegates to another, with a hook and a delay around each call."""

    def __init__(self, inner: Any, *, before: Any = None, delay: float = 0.0) -> None:
        self.inner, self.before, self.delay = inner, before, delay
        self.active = self.peak = 0

    async def complete(self, ctx: Any, messages: Any, schema: Any, tier: str = "strong") -> Any:
        if self.before is not None:
            await self.before(ctx)
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            return await self.inner.complete(ctx, messages, schema, tier)
        finally:
            self.active -= 1


async def rows(app_db: Database, scene: Any) -> list[Evaluation]:
    async with app_db.tenant(scene.organization_id) as session:
        found = await session.scalars(
            select(Evaluation)
            .where(Evaluation.interview_id == scene.interview_id)
            .order_by(Evaluation.sequence)
        )
        return list(found.all())


async def running_row(admin_engine: AsyncEngine, scene: Any, *, age_minutes: int) -> None:
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO evaluations (id, organization_id, interview_id, sequence, "
                "prompt_version, rubric_version, evaluation_version, updated_at) VALUES "
                "(gen_random_uuid(), :org, :iv, 1, 'p', 'r', 'e', :at)"
            ),
            {
                "org": scene.organization_id,
                "iv": scene.interview_id,
                "at": datetime.now(UTC) - timedelta(minutes=age_minutes),
            },
        )


async def test_a_duplicate_event_for_a_live_run_never_gives_up_the_live_run(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: Any,
    make_completed_interview: Any,
) -> None:
    scene = await make_completed_interview(await make_organization("Acme"), status="evaluating")
    await running_row(admin_engine, scene, age_minutes=0)
    payload = {"action": "evaluate", "interview_id": str(scene.interview_id)}
    ai = mock_ai(app_db)
    with pytest.raises(EvaluationBusy):
        await handle_evaluation_event(app_db, ai, scene.organization_id, payload)
    await give_up_evaluation(app_db, scene.organization_id, payload)
    [live] = await rows(app_db, scene)
    assert live.status == "running"
    async with app_db.tenant(scene.organization_id) as session:
        assert (await session.get_one(Interview, scene.interview_id)).status == "evaluating"


async def test_a_run_that_stopped_is_given_up(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: Any,
    make_completed_interview: Any,
) -> None:
    scene = await make_completed_interview(await make_organization("Acme"), status="evaluating")
    await running_row(admin_engine, scene, age_minutes=30)
    await give_up_evaluation(
        app_db,
        scene.organization_id,
        {"action": "evaluate", "interview_id": str(scene.interview_id)},
    )
    [stopped] = await rows(app_db, scene)
    assert stopped.status == "failed" and stopped.error == "gave_up"
    async with app_db.tenant(scene.organization_id) as session:
        assert (await session.get_one(Interview, scene.interview_id)).status == "completed"


async def test_a_run_keeps_itself_alive_between_questions(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: Any,
    make_completed_interview: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service, "CONCURRENCY", 1)
    scene = await make_completed_interview(await make_organization("Acme"))
    seen: list[bool] = []

    async def before(ctx: Any) -> None:
        if ctx.purpose != "evaluation.synthesis":
            return
        async with admin_engine.begin() as conn:
            seen.append(
                bool(
                    await conn.scalar(
                        text(
                            "SELECT updated_at > created_at FROM evaluations "
                            "WHERE interview_id = :iv"
                        ),
                        {"iv": scene.interview_id},
                    )
                )
            )

    llm = Spy(mock_ai(app_db).llm, before=before)
    await evaluate_interview(app_db, llm, scene.organization_id, scene.interview_id)
    assert seen == [True]


async def test_a_run_that_was_taken_over_stores_nothing(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: Any,
    make_completed_interview: Any,
) -> None:
    scene = await make_completed_interview(await make_organization("Acme"))

    async def take_over(ctx: Any) -> None:
        if ctx.purpose == "evaluation.synthesis":
            async with admin_engine.begin() as conn:
                await conn.execute(
                    text("UPDATE evaluations SET status = 'failed' WHERE interview_id = :iv"),
                    {"iv": scene.interview_id},
                )

    llm = Spy(mock_ai(app_db).llm, before=take_over)
    with pytest.raises(EvaluationLost):
        await evaluate_interview(app_db, llm, scene.organization_id, scene.interview_id)
    async with app_db.tenant(scene.organization_id) as session:
        assert (await session.get_one(Interview, scene.interview_id)).status == "evaluating"
        assert (await session.scalars(select(QuestionEvaluation))).all() == []


@pytest.mark.parametrize("purpose", ["evaluation.question", "evaluation.synthesis"])
async def test_an_unusable_reply_fails_the_run_so_it_can_be_redone(
    app_db: Database,
    make_organization: Any,
    make_completed_interview: Any,
    purpose: str,
) -> None:
    scene = await make_completed_interview(await make_organization("Acme"))
    fail = [True]

    async def break_once(ctx: Any) -> None:
        if ctx.purpose == purpose and fail:
            fail.pop()
            raise AiOutputInvalid("not the schema")

    llm = Spy(mock_ai(app_db).llm, before=break_once)
    with pytest.raises(AiOutputInvalid):
        await evaluate_interview(app_db, llm, scene.organization_id, scene.interview_id)
    [failed] = await rows(app_db, scene)
    assert failed.status == "failed" and failed.error == "invalid_output"
    async with app_db.tenant(scene.organization_id) as session:
        assert (await session.get_one(Interview, scene.interview_id)).status == "evaluating"
    redone = await evaluate_interview(app_db, llm, scene.organization_id, scene.interview_id)
    assert redone is not None and redone.status == "ready" and redone.sequence == 2
    async with app_db.tenant(scene.organization_id) as session:
        count = len(
            (
                await session.scalars(
                    select(QuestionEvaluation).where(QuestionEvaluation.evaluation_id == redone.id)
                )
            ).all()
        )
    assert count == 3


async def test_questions_run_concurrently_within_a_bound(
    app_db: Database,
    make_organization: Any,
    make_completed_interview: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scene = await make_completed_interview(await make_organization("Acme"))
    wide = Spy(mock_ai(app_db).llm, delay=0.05)
    await evaluate_interview(app_db, wide, scene.organization_id, scene.interview_id)
    assert wide.peak == 3  # all three questions at once, the synthesis alone after them

    other = await make_completed_interview(await make_organization("Globex"))
    monkeypatch.setattr(service, "CONCURRENCY", 2)
    narrow = Spy(mock_ai(app_db).llm, delay=0.05)
    await evaluate_interview(app_db, narrow, other.organization_id, other.interview_id)
    assert narrow.peak == 2


def test_the_evaluations_model_is_the_questions_not_the_summarys() -> None:
    added: list[Any] = []
    evaluation = SimpleNamespace(
        organization_id=None, id=None, interview_id=None, pinned={}, status="running"
    )
    score = SimpleNamespace(
        question_id="00000000-0000-0000-0000-000000000001",
        skill=None,
        kind="main",
        weight=1.0,
        dimensions={},
        overall=5.0,
        unsupported=[],
        missing_concepts=[],
        note="",
        flags=[],
        model="zz-question-model",
        input_digest="d",
    )
    aggregate = SimpleNamespace(
        overall=5.0,
        communication=SimpleNamespace(score=5.0),
        skills=[],
        flags=[],
        follow_ups={"asked": 0, "mean": None, "main_mean": None, "delta": None},
        coding={},
        communication_json=None,
    )
    aggregate.communication.as_json = lambda: {}  # type: ignore[attr-defined]
    scored = service._Scored(
        [score],  # type: ignore[list-item]
        aggregate,  # type: ignore[arg-type]
        Synthesis([], [], EMPTY, EMPTY, "aa-summary-model"),
    )
    service._store(SimpleNamespace(add=added.append), evaluation, scored)  # type: ignore[arg-type]
    assert evaluation.model == "zz-question-model"
    assert evaluation.pinned["models"] == ["aa-summary-model", "zz-question-model"]


async def test_a_rerun_that_can_never_work_is_recorded_once_not_retried(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: Any,
    make_completed_interview: Any,
) -> None:
    scene = await make_completed_interview(await make_organization("Acme"))
    ai = mock_ai(app_db)
    await evaluate_interview(app_db, ai.llm, scene.organization_id, scene.interview_id)
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE evaluations SET evaluation_version = 'evaluation-v0'"),
        )
    async with app_db.tenant(scene.organization_id) as session:
        base = (await session.scalars(select(Evaluation))).one()
    with pytest.raises(Unreproducible):
        check_reproducible(base)
    payload = {"action": "rerun", "interview_id": str(scene.interview_id)}
    await handle_evaluation_event(app_db, ai, scene.organization_id, payload)  # no raise
    first, second = await rows(app_db, scene)
    assert second.kind == "rerun" and second.status == "failed"
    assert second.error == "evaluation-not-reproducible" and second.rerun_of == first.id
