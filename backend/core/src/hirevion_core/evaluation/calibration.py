"""Human calibration (PRD §44 "store evidence", master plan §6.9): reviewers record their own
scores for a question, and the organisation's agreement with the AI is measured.

A reviewer scores any of the eight dimensions from 0 to 10, and may change their scores later.
The web panel asks for them before showing the AI's (so the AI's number can't anchor them), but
the API does not hide the evaluation: reading it is `reports.interview.view`. Agreement is over
dimension pairs (the AI's verified score and a reviewer's) from the interviews' current
evaluations: weighted kappa and Spearman (`agreement`), the mean gap and the share within a
point, overall and per dimension, and the AI's bias (its mean score minus the reviewers').
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.actor import Actor
from hirevion_core.access.audit import record
from hirevion_core.access.errors import Conflict, Invalid, NotFound
from hirevion_core.evaluation import agreement as stats
from hirevion_core.evaluation.registry import DIMENSIONS
from hirevion_core.evaluation.scoring import SCORED_KINDS
from hirevion_core.models import (
    Evaluation,
    HumanScore,
    Interview,
    InterviewQuestion,
    QuestionEvaluation,
)

REVIEWABLE = ("completed", "evaluating", "evaluated")
NOTE_MAX = 1_000


def _clean(dimensions: Mapping[str, Any]) -> dict[str, float]:
    if not dimensions:
        raise Invalid("scores-required", "Score at least one dimension", field="dimensions")
    cleaned: dict[str, float] = {}
    for name, value in dimensions.items():
        if name not in DIMENSIONS:
            raise Invalid("unknown-dimension", f"{name} is not a dimension", field="dimensions")
        if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= value <= 10:
            raise Invalid("invalid-score", "Scores run from 0 to 10", field=f"dimensions.{name}")
        cleaned[name] = round(float(value), 1)
    return cleaned


async def record_human_scores(
    session: AsyncSession,
    actor: Actor,
    interview: Interview,
    question_id: UUID,
    dimensions: Mapping[str, Any],
    note: str = "",
) -> HumanScore:
    """Saves the actor's scores for one question (replacing any they saved before)."""
    scores = _clean(dimensions)
    if interview.status not in REVIEWABLE:
        raise Conflict("not-reviewable", "The interview hasn't finished yet")
    question = await session.get(InterviewQuestion, question_id)
    if question is None or question.interview_id != interview.id:
        raise NotFound("question-not-found", "No such question in this interview")
    if question.kind not in SCORED_KINDS:
        raise Invalid("question-not-scored", "That question isn't scored", field="question_id")
    row = await session.scalar(
        select(HumanScore).where(
            HumanScore.question_id == question_id, HumanScore.reviewer_id == actor.user_id
        )
    )
    note = note.strip()[:NOTE_MAX]
    if row is None:
        row = HumanScore(
            organization_id=interview.organization_id,
            interview_id=interview.id,
            question_id=question_id,
            reviewer_id=actor.user_id,
            dimensions=scores,
            note=note,
        )
        session.add(row)
    else:
        row.dimensions, row.note = scores, note
    await session.flush()
    await record(
        session,
        actor,
        "evaluation.human_scored",
        "interview",
        interview.id,
        details={"question_id": str(question_id), "dimensions": sorted(scores)},
    )
    await session.refresh(row)
    return row


async def own_scores(
    session: AsyncSession, interview_id: UUID, reviewer_id: UUID
) -> list[HumanScore]:
    rows = await session.scalars(
        select(HumanScore)
        .where(HumanScore.interview_id == interview_id, HumanScore.reviewer_id == reviewer_id)
        .order_by(HumanScore.created_at)
    )
    return list(rows.all())


async def agreement(session: AsyncSession) -> dict[str, Any]:
    """The organisation's agreement between reviewers and the AI (the session's tenant)."""
    humans = (await session.scalars(select(HumanScore))).all()
    scored = {human.question_id for human in humans}
    if not scored:
        current: dict[UUID, QuestionEvaluation] = {}
    else:
        # Only the evaluations of questions a reviewer scored.
        current = {
            row.question_id: row
            for row in (
                await session.scalars(
                    select(QuestionEvaluation)
                    .join(Evaluation, Evaluation.id == QuestionEvaluation.evaluation_id)
                    .where(
                        Evaluation.kind == "initial",
                        Evaluation.status == "ready",
                        QuestionEvaluation.question_id.in_(scored),
                    )
                )
            ).all()
        }
    pairs: list[tuple[float, float]] = []
    by_dimension: dict[str, list[tuple[float, float]]] = defaultdict(list)
    compared: set[tuple[UUID, UUID]] = set()
    for human in humans:
        ai = current.get(human.question_id)
        if ai is None:
            continue
        for name, given in human.dimensions.items():
            item = ai.dimensions.get(name)
            if item is None:
                continue
            pair = (float(item["score"]), float(given))
            pairs.append(pair)
            by_dimension[name].append(pair)
        compared.add((human.question_id, human.reviewer_id))
    bias = round(sum(a - h for a, h in pairs) / len(pairs), 4) if pairs else None
    return {
        "pairs": len(pairs),
        "questions": len({question for question, _ in compared}),
        "reviewers": len({reviewer for _, reviewer in compared}),
        "overall": stats.summary(pairs),
        "by_dimension": {
            name: stats.summary(by_dimension[name]) for name in DIMENSIONS if name in by_dimension
        },
        "bias": bias,
    }
