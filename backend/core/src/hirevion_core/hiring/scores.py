"""Changing a score (PRD §97 "Score modified"). The evaluation is the AI's record and is never
edited; a person's change is a new `score_changes` row with the reason, and the latest change of
a score is the one that shows beside the AI's. A change to a skill or a question does not
recompute the overall score: each score is its own to change."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.actor import Actor
from hirevion_core.access.audit import record
from hirevion_core.access.errors import Conflict, Invalid
from hirevion_core.models import Evaluation, Interview, QuestionEvaluation, ScoreChange
from hirevion_core.models.reporting import SCORE_SCOPES

REASON_MAX = 1000


@dataclass(frozen=True, slots=True)
class ScoreValue:
    ai: float | None
    """What the evaluator gave; None when it scored nothing here."""
    value: float | None
    """What shows: the latest change, else the AI's."""
    change: ScoreChange | None = None


@dataclass(slots=True)
class ScoreView:
    evaluation_id: UUID
    overall: ScoreValue
    communication: ScoreValue
    skills: dict[str, ScoreValue] = field(default_factory=dict)
    questions: dict[str, ScoreValue] = field(default_factory=dict)
    changes: list[ScoreChange] = field(default_factory=list)
    """Every change, newest first."""


def _number(value: Decimal | float | None) -> float | None:
    return float(value) if value is not None else None


async def latest_evaluation(session: AsyncSession, interview_id: UUID) -> Evaluation | None:
    """The interview's own (initial) evaluation, once it is ready."""
    return await session.scalar(
        select(Evaluation)
        .where(
            Evaluation.interview_id == interview_id,
            Evaluation.kind == "initial",
            Evaluation.status == "ready",
        )
        .order_by(Evaluation.sequence.desc())
        .limit(1)
    )


async def _ai_scores(
    session: AsyncSession,
    evaluation: Evaluation,
    question_evaluations: Mapping[UUID, QuestionEvaluation] | None,
) -> tuple[dict[str, float | None], dict[str, float | None]]:
    skills = {str(item["skill"]): _number(item.get("score")) for item in evaluation.skills}
    if question_evaluations is not None:
        return skills, {
            str(question): _number(row.overall_score)
            for question, row in question_evaluations.items()
        }
    rows = await session.execute(
        select(QuestionEvaluation.question_id, QuestionEvaluation.overall_score).where(
            QuestionEvaluation.evaluation_id == evaluation.id
        )
    )
    return skills, {str(question): _number(score) for question, score in rows}


async def _changes(session: AsyncSession, interview_id: UUID) -> list[ScoreChange]:
    rows = await session.scalars(
        select(ScoreChange)
        .where(ScoreChange.interview_id == interview_id)
        .order_by(ScoreChange.created_at.desc(), ScoreChange.id.desc())
    )
    return list(rows.all())


def _value(ai: float | None, change: ScoreChange | None) -> ScoreValue:
    return ScoreValue(ai, float(change.new_score) if change is not None else ai, change)


async def score_view(
    session: AsyncSession,
    interview: Interview,
    *,
    evaluation: Evaluation | None = None,
    question_evaluations: Mapping[UUID, QuestionEvaluation] | None = None,
) -> ScoreView:
    """The evaluation's scores with the people's changes laid over them. A caller that has
    already read the evaluation (and its questions') passes them in so they are read once."""
    evaluation = evaluation or await latest_evaluation(session, interview.id)
    if evaluation is None:
        raise Conflict("not-evaluated", "The interview has no evaluation yet")
    skills, questions = await _ai_scores(session, evaluation, question_evaluations)
    changes = await _changes(session, interview.id)
    latest: dict[tuple[str, str | None], ScoreChange] = {}
    for change in changes:  # newest first: the first seen is the latest
        latest.setdefault((change.scope, change.target), change)
    return ScoreView(
        evaluation_id=evaluation.id,
        overall=_value(_number(evaluation.overall_score), latest.get(("overall", None))),
        communication=_value(
            _number(evaluation.communication_score), latest.get(("communication", None))
        ),
        skills={name: _value(score, latest.get(("skill", name))) for name, score in skills.items()},
        questions={
            question: _value(score, latest.get(("question", question)))
            for question, score in questions.items()
        },
        changes=changes,
    )


def _current(view: ScoreView, scope: str, target: str | None) -> ScoreValue | None:
    if scope == "overall" and target is None:
        return view.overall
    if scope == "communication" and target is None:
        return view.communication
    if scope == "skill" and target is not None:
        return view.skills.get(target)
    if scope == "question" and target is not None:
        return view.questions.get(target)
    return None


async def change_score(
    session: AsyncSession,
    actor: Actor,
    interview: Interview,
    scope: str,
    target: str | None,
    new_score: float,
    reason: str,
) -> ScoreChange:
    """Records a person's change of one score and audits it. `target` is the skill's name or the
    question's id; overall and communication take none."""
    if scope not in SCORE_SCOPES:
        raise Invalid("invalid-scope", "Choose what to change", field="scope")
    view = await score_view(session, interview)
    current = _current(view, scope, target)
    if current is None:
        raise Invalid(
            "unknown-target", "That isn't something the evaluation scored", field="target"
        )
    if isinstance(new_score, bool) or not 0 <= new_score <= 10:
        raise Invalid("invalid-score", "Scores run from 0 to 10", field="new_score")
    note = reason.strip()
    if not note or len(note) > REASON_MAX:
        raise Invalid("reason-required", "Say why the score changes", field="reason")
    score = Decimal(str(new_score)).quantize(Decimal("0.01"))
    if current.value is not None and Decimal(str(current.value)).quantize(Decimal("0.01")) == score:
        raise Conflict("no-change", "The score is already that")
    row = ScoreChange(
        organization_id=interview.organization_id,
        interview_id=interview.id,
        evaluation_id=view.evaluation_id,
        scope=scope,
        target=target,
        previous_score=Decimal(str(current.value)).quantize(Decimal("0.01"))
        if current.value is not None
        else None,
        new_score=score,
        reason=note,
        changed_by=actor.user_id,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    details: dict[str, Any] = {
        "scope": scope,
        "target": target,
        "previous": float(row.previous_score) if row.previous_score is not None else None,
        "new": float(score),
        "ai": current.ai,
        "reason": note,
        "evaluation_id": str(view.evaluation_id),
    }
    await record(session, actor, "score.modified", "interview", interview.id, details=details)
    return row
