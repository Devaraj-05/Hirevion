"""Evaluating an interview after it ends, and repeating an evaluation with its pinned versions
(PRD §44, §70, §79; ADR-0031).

`evaluate_interview` is the `evaluation` consumer's work, in three steps so no transaction is
open while a model thinks:

1. one transaction moves the interview `completed → evaluating`, reads what the evaluator needs
   and records a `running` evaluation with the versions in force;
2. the model calls: one per answered question, then the synthesis;
3. one transaction writes the scores, moves the interview `evaluating → evaluated` and queues
   `evaluation.completed`.

A failure in step 2 or 3 marks the evaluation failed and leaves the interview `evaluating`, so
the stream's retry starts a new run; the last retry's give-up (`runner.give_up_evaluation`)
returns the interview to `completed`. `rerun_pinned` repeats the latest evaluation with the
prompt, rubric weights and skill plan it recorded and stores the difference; it never changes the
interview or the evaluation it checks.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.errors import Conflict
from hirevion_core.ai.types import AiError, AiOutputInvalid, AiRequestError, LLMService
from hirevion_core.audit import AuditEntry, AuditService
from hirevion_core.db.session import Database
from hirevion_core.evaluation import registry
from hirevion_core.evaluation.aggregate import (
    EMPTY,
    Aggregate,
    SkillPlan,
    Synthesis,
    Synthesizer,
    aggregate,
)
from hirevion_core.evaluation.compare import Snapshot, Tolerance, compare
from hirevion_core.evaluation.inputs import EvaluationInputs, load_inputs, skills_json
from hirevion_core.evaluation.registry import Rubric, rubric_from_weights
from hirevion_core.evaluation.scoring import QuestionCase, QuestionEvaluator, QuestionScore
from hirevion_core.interviews.lifecycle import By, interview_payload, transition
from hirevion_core.models import Evaluation, Interview, QuestionEvaluation
from hirevion_core.outbox import publish_event

log = logging.getLogger(__name__)

COMPLETED_TOPIC = "evaluation.completed"
STALE_AFTER = timedelta(minutes=10)
BY = By("system", "evaluator")
__all__ = [
    "BY",
    "EvaluationBusy",
    "NothingToRerun",
    "Tolerance",
    "Unreproducible",
    "evaluate_interview",
    "rerun_pinned",
]


class EvaluationBusy(RuntimeError):
    """Another run of this interview's evaluation is in progress; try again later."""


class NothingToRerun(Conflict):
    def __init__(self) -> None:
        super().__init__("nothing-to-rerun", "This interview has no finished evaluation to repeat")


class Unreproducible(Conflict):
    def __init__(self, detail: str) -> None:
        super().__init__(
            "evaluation-not-reproducible",
            "That evaluation can't be reproduced with this version of the software",
            detail=detail,
        )


@dataclass(slots=True)
class _Scored:
    scores: list[QuestionScore]
    aggregate: Aggregate
    synthesis: Synthesis
    flags: list[str]


def _now() -> datetime:
    return datetime.now(UTC)


def _decimal(value: float | None) -> Decimal | None:
    return Decimal(str(round(value, 2))) if value is not None else None


async def _next_sequence(session: AsyncSession, interview_id: UUID) -> int:
    top = await session.scalar(
        select(func.max(Evaluation.sequence)).where(Evaluation.interview_id == interview_id)
    )
    return (top or 0) + 1


async def _latest(
    session: AsyncSession, interview_id: UUID, *, kind: str, status: str
) -> Evaluation | None:
    return await session.scalar(
        select(Evaluation)
        .where(
            Evaluation.interview_id == interview_id,
            Evaluation.kind == kind,
            Evaluation.status == status,
        )
        .order_by(Evaluation.sequence.desc())
        .limit(1)
    )


def _pinned(inputs: EvaluationInputs, rubric: Rubric, synthesis_prompt: str) -> dict[str, Any]:
    return {
        "rubric": {"base": rubric.base, "weights": rubric.weights, "version": rubric.version},
        "skills": skills_json(inputs.plan),
        "question_prompt_version": registry.ACTIVE_QUESTION_PROMPT,
        "synthesis_prompt_version": synthesis_prompt,
        "tier": "strong",
        "inputs": {"questions": len(inputs.cases), "candidate_segments": inputs.segments},
    }


async def _score_all(
    llm: LLMService,
    organization_id: UUID,
    cases: Sequence[QuestionCase],
    plan: Sequence[SkillPlan],
    rubric: Rubric,
    evaluator: QuestionEvaluator,
    synthesizer: Synthesizer,
    refs: Mapping[str, str],
) -> _Scored:
    """The model calls. Unavailable models and spent budgets propagate (the run is retried); an
    unusable reply costs that question its score and is flagged."""
    scores: list[QuestionScore] = []
    flags: list[str] = []
    for case in cases:
        try:
            scores.append(await evaluator.evaluate(organization_id, case, rubric, refs=refs))
        except (AiOutputInvalid, AiRequestError) as error:
            log.warning("Question %s could not be evaluated: %s", case.question_id, error)
            flags.append(f"question_not_evaluated:{case.question_id}")
    result = aggregate(scores, plan, rubric)
    try:
        synthesis = await synthesizer.synthesize(
            organization_id, scores, cases, result, rubric, refs=refs
        )
    except (AiOutputInvalid, AiRequestError) as error:
        log.warning("The synthesis could not be written: %s", error)
        flags.append("synthesis_failed")
        synthesis = Synthesis([], [], EMPTY, EMPTY, None)
    return _Scored(scores, result, synthesis, flags)


def _summary(scored: _Scored) -> dict[str, Any]:
    result, synthesis = scored.aggregate, scored.synthesis
    return {
        "strengths": [f.as_json() for f in synthesis.strengths],
        "knowledge_gaps": [f.as_json() for f in synthesis.gaps],
        "follow_up_performance": {**result.follow_ups, "summary": synthesis.follow_up.as_json()},
        "communication": {
            **result.communication.as_json(),
            "summary": synthesis.communication.as_json(),
        },
        "coding": result.coding,
    }


def _store(
    session: AsyncSession,
    evaluation: Evaluation,
    scored: _Scored,
    rubric: Rubric,
    inputs: EvaluationInputs,
) -> None:
    result = scored.aggregate
    used = {s.model for s in scored.scores}
    if scored.synthesis.model:
        used.add(scored.synthesis.model)
    models = sorted(used)
    evaluation.status = "ready"
    evaluation.model = models[0] if models else None
    evaluation.pinned = {**evaluation.pinned, "models": models}
    evaluation.overall_score = _decimal(result.overall)
    evaluation.communication_score = _decimal(result.communication.score)
    evaluation.skills = [skill.as_json() for skill in result.skills]
    evaluation.summary = _summary(scored)
    evaluation.flags = [*result.flags, *scored.flags]
    evaluation.completed_at = _now()
    for score in scored.scores:
        session.add(
            QuestionEvaluation(
                organization_id=evaluation.organization_id,
                evaluation_id=evaluation.id,
                interview_id=evaluation.interview_id,
                question_id=UUID(score.question_id),
                skill=score.skill,
                kind=score.kind,
                weight=Decimal(str(score.weight)),
                dimensions={n: d.as_json() for n, d in score.dimensions.items()},
                overall_score=_decimal(score.overall),
                unsupported=score.unsupported,
                missing_concepts=score.missing_concepts,
                note=score.note,
                flags=score.flags,
                model=score.model,
                input_digest=score.input_digest,
            )
        )


async def _fail(db: Database, organization_id: UUID, evaluation_id: UUID, error: Exception) -> None:
    code = error.code if isinstance(error, AiError) else type(error).__name__
    try:
        async with db.tenant(organization_id) as session:
            evaluation = await session.get(Evaluation, evaluation_id)
            if evaluation is not None and evaluation.status == "running":
                evaluation.status = "failed"
                evaluation.error = code
                evaluation.completed_at = _now()
    except Exception:
        log.exception("Marking evaluation %s failed did not work", evaluation_id)


async def evaluate_interview(
    db: Database, llm: LLMService, organization_id: UUID, interview_id: UUID
) -> Evaluation | None:
    """Evaluates a completed interview (idempotent); returns None when there is nothing to
    evaluate. Raises the provider layer's errors, or `EvaluationBusy`, for the consumer to retry."""
    async with db.tenant(organization_id) as session:
        interview = await session.get(Interview, interview_id, with_for_update=True)
        if interview is None:
            return None
        ready = await _latest(session, interview_id, kind="initial", status="ready")
        if ready is not None:
            return ready
        if interview.status not in ("completed", "evaluating"):
            return None
        running = await _latest(session, interview_id, kind="initial", status="running")
        if running is not None:
            if _now() - running.updated_at < STALE_AFTER:
                raise EvaluationBusy(f"interview {interview_id} is being evaluated")
            running.status, running.error = "failed", "stale"
            await session.flush()
        if interview.status == "completed":
            await transition(session, interview, "evaluating", "evaluation_started", BY)
        inputs = await load_inputs(session, interview)
        rubric = inputs.rubric
        evaluation = Evaluation(
            organization_id=organization_id,
            interview_id=interview_id,
            sequence=await _next_sequence(session, interview_id),
            kind="initial",
            status="running",
            prompt_version=registry.ACTIVE_QUESTION_PROMPT,
            rubric_version=rubric.version,
            evaluation_version=registry.EVALUATION_VERSION,
            pinned=_pinned(inputs, rubric, registry.ACTIVE_SYNTHESIS_PROMPT),
        )
        session.add(evaluation)
        await session.flush()
        evaluation_id = evaluation.id
    refs = {"interview": str(interview_id), "evaluation": str(evaluation_id)}
    try:
        scored = await _score_all(
            llm,
            organization_id,
            inputs.cases,
            inputs.plan,
            rubric,
            QuestionEvaluator(llm),
            Synthesizer(llm),
            refs,
        )
        async with db.tenant(organization_id) as session:
            interview = await session.get_one(Interview, interview_id, with_for_update=True)
            evaluation = await session.get_one(Evaluation, evaluation_id)
            _store(session, evaluation, scored, rubric, inputs)
            await session.flush()
            await transition(
                session,
                interview,
                "evaluated",
                "evaluated",
                BY,
                details={"evaluation_id": str(evaluation_id)},
            )
            await publish_event(
                session,
                organization_id,
                COMPLETED_TOPIC,
                {
                    **interview_payload(interview),
                    "evaluation_id": str(evaluation_id),
                    "evaluation_version": evaluation.evaluation_version,
                    "overall_score": float(evaluation.overall_score)
                    if evaluation.overall_score is not None
                    else None,
                },
                key=str(interview_id),
            )
            return evaluation
    except Exception as error:
        await _fail(db, organization_id, evaluation_id, error)
        raise


def _snapshots(rows: Sequence[QuestionEvaluation]) -> dict[str, Snapshot]:
    return {
        str(row.question_id): Snapshot(
            float(row.overall_score),
            {name: float(d["score"]) for name, d in row.dimensions.items()},
            row.input_digest,
        )
        for row in rows
    }


async def rerun_pinned(
    db: Database,
    llm: LLMService,
    organization_id: UUID,
    interview_id: UUID,
    requested_by: UUID | None,
    tolerance: Tolerance | None = None,
) -> Evaluation:
    """Repeats the interview's latest evaluation with the prompt, rubric weights and skill plan
    it recorded, and stores the run with its difference from the original (`diff`)."""
    tolerance = tolerance or Tolerance()
    async with db.tenant(organization_id) as session:
        interview = await session.get(Interview, interview_id, with_for_update=True)
        base = (
            await _latest(session, interview_id, kind="initial", status="ready")
            if interview is not None
            else None
        )
        if interview is None or base is None:
            raise NothingToRerun
        if base.evaluation_version not in registry.SUPPORTED_EVALUATION_VERSIONS:
            raise Unreproducible(f"it used {base.evaluation_version}")
        pinned = base.pinned
        try:
            rubric = rubric_from_weights(
                pinned["rubric"]["weights"], registry.rubric_base(base.rubric_version)
            )
            plan = [
                SkillPlan(str(s["name"]), float(s["weight"]), bool(s.get("required")))
                for s in pinned["skills"]
            ]
            evaluator = QuestionEvaluator(
                llm,
                prompt_version=base.prompt_version,
                rubric_base=rubric.base,
                evaluation_version=base.evaluation_version,
            )
            synthesizer = Synthesizer(
                llm,
                prompt_version=str(pinned["synthesis_prompt_version"]),
                evaluation_version=base.evaluation_version,
            )
        except (registry.UnknownVersion, KeyError) as error:
            raise Unreproducible(str(error)) from error
        base_rows = (
            await session.scalars(
                select(QuestionEvaluation).where(QuestionEvaluation.evaluation_id == base.id)
            )
        ).all()
        inputs = await load_inputs(session, interview)
        evaluation = Evaluation(
            organization_id=organization_id,
            interview_id=interview_id,
            sequence=await _next_sequence(session, interview_id),
            kind="rerun",
            rerun_of=base.id,
            status="running",
            prompt_version=base.prompt_version,
            rubric_version=base.rubric_version,
            evaluation_version=base.evaluation_version,
            pinned=dict(pinned),
            created_by=requested_by,
        )
        session.add(evaluation)
        await session.flush()
        evaluation_id = evaluation.id
        base_snapshots = _snapshots(base_rows)
        base_overall = float(base.overall_score) if base.overall_score is not None else None
        base_model = base.model
    refs = {
        "interview": str(interview_id),
        "evaluation": str(evaluation_id),
        "rerun_of": str(base.id),
    }
    try:
        scored = await _score_all(
            llm, organization_id, inputs.cases, plan, rubric, evaluator, synthesizer, refs
        )
        rerun_overall = scored.aggregate.overall
        models = sorted({s.model for s in scored.scores})
        diff = compare(
            base_snapshots,
            {
                s.question_id: Snapshot(
                    s.overall, {n: d.score for n, d in s.dimensions.items()}, s.input_digest
                )
                for s in scored.scores
            },
            tolerance=tolerance,
            base_overall=base_overall,
            rerun_overall=rerun_overall,
            base_model=base_model,
            rerun_model=models[0] if models else None,
        )
        async with db.tenant(organization_id) as session:
            evaluation = await session.get_one(Evaluation, evaluation_id)
            _store(session, evaluation, scored, rubric, inputs)
            evaluation.diff = diff
            await session.flush()
            await AuditService().append(
                session,
                organization_id,
                AuditEntry(
                    action="evaluation.rerun",
                    resource_type="interview",
                    resource_id=str(interview_id),
                    actor_type="user" if requested_by else "system",
                    actor_id=str(requested_by) if requested_by else "cli",
                    details={
                        "evaluation_id": str(evaluation_id),
                        "rerun_of": str(base.id),
                        "within_tolerance": diff["within_tolerance"],
                        "max_dimension_diff": diff["max_dimension_diff"],
                    },
                ),
            )
            return evaluation
    except Exception as error:
        await _fail(db, organization_id, evaluation_id, error)
        raise
