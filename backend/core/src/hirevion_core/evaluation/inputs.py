"""What the evaluator reads about a finished interview: its answered questions with the
candidate's turns from the stored transcript, the skills' plan and the rubric.

Only candidate turns that match a stored answer are used. An utterance that was not an answer (a
request to repeat, a try at instructing the AI) is in the transcript but is never sent to a model
or cited as evidence. The introduction, the final questions and coding are not scored here.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.engine.analysis import ANSWER_MAX
from hirevion_core.evaluation.aggregate import SkillPlan
from hirevion_core.evaluation.evidence import Turn
from hirevion_core.evaluation.registry import Rubric, rubric_from_policy
from hirevion_core.evaluation.scoring import SCORED_KINDS, ParentContext, QuestionCase
from hirevion_core.models import (
    Interview,
    InterviewAnswer,
    InterviewQuestion,
    InterviewSession,
    TranscriptSegment,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EvaluationInputs:
    cases: list[QuestionCase]
    plan: list[SkillPlan]
    rubric: Rubric
    segments: int


def _norm(text: str) -> str:
    return " ".join(text.split())


def _is_answer(segment: str, answer: str) -> bool:
    a, b = _norm(segment), _norm(answer)
    return a == b or (len(b) >= ANSWER_MAX - 50 and a.startswith(b))  # stored answers are cut


def plan_from(state: Mapping[str, Any] | None, policy: Mapping[str, Any]) -> list[SkillPlan]:
    """The skills the interview was planned around: the engine's (which add the job's required
    skills), else the template's."""
    skills = (state or {}).get("skills") or policy.get("skills") or []
    plan = []
    for item in skills:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        weight = item.get("weight")
        plan.append(
            SkillPlan(
                name,
                float(weight) if isinstance(weight, int | float) and weight > 0 else 1.0,
                bool(item.get("required")),
            )
        )
    return plan


def _question_rubrics(state: Mapping[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    pool = (state or {}).get("pool") or []
    return {str(item.get("text")): list(item.get("rubric") or []) for item in pool}


async def load_inputs(session: AsyncSession, interview: Interview) -> EvaluationInputs:
    questions = (
        await session.scalars(
            select(InterviewQuestion)
            .where(InterviewQuestion.interview_id == interview.id)
            .order_by(InterviewQuestion.position)
        )
    ).all()
    answers = (
        await session.scalars(
            select(InterviewAnswer)
            .where(InterviewAnswer.interview_id == interview.id)
            .order_by(InterviewAnswer.created_at)
        )
    ).all()
    segments = (
        await session.scalars(
            select(TranscriptSegment)
            .where(
                TranscriptSegment.interview_id == interview.id,
                TranscriptSegment.speaker == "candidate",
            )
            .order_by(TranscriptSegment.seq)
        )
    ).all()
    row = await session.get(InterviewSession, interview.id)
    state = row.state if row is not None and row.state else None
    rubrics = _question_rubrics(state)

    answers_by: dict[Any, list[InterviewAnswer]] = {}
    for answer in answers:
        answers_by.setdefault(answer.question_id, []).append(answer)
    by_id = {q.id: q for q in questions}

    def turns_for(question: InterviewQuestion) -> list[Turn]:
        given = answers_by.get(question.id, [])
        return [
            Turn(s.seq, s.text, s.start_ms, s.end_ms, str(question.id))
            for s in segments
            if s.question_id == question.id and any(_is_answer(s.text, a.text) for a in given)
        ]

    cases: list[QuestionCase] = []
    for question in questions:
        if question.kind not in SCORED_KINDS or question.id not in answers_by:
            continue
        turns = turns_for(question)
        if not turns:
            log.warning("Question %s has an answer but no stored transcript turn", question.id)
            continue
        given = answers_by[question.id]
        parent = by_id.get(question.parent_id) if question.parent_id else None
        flags = sorted({flag for a in given for flag in a.flags})
        cases.append(
            QuestionCase(
                question_id=str(question.id),
                kind=question.kind,
                skill=question.skill,
                difficulty=question.difficulty,
                text=question.text,
                turns=turns,
                expected_concepts=list(question.expected_concepts),
                question_rubric=rubrics.get(question.text, []),
                parent=ParentContext(
                    parent.text, " ".join(a.text for a in answers_by.get(parent.id, []))
                )
                if parent is not None
                else None,
                flags=flags,
                late=any(a.late for a in given),
            )
        )
    return EvaluationInputs(
        cases=cases,
        plan=plan_from(state, interview.policy),
        rubric=rubric_from_policy(interview.policy.get("rubric")),
        segments=len(segments),
    )


def skills_json(plan: Sequence[SkillPlan]) -> list[dict[str, Any]]:
    return [{"name": s.name, "weight": s.weight, "required": s.required} for s in plan]
