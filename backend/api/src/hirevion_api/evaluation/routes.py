"""The recruiter's view of an interview's evaluation (SP-10; PRD §44, §70, §79): the final
evaluation with its skills, strengths, gaps and evidence; each question's eight scores; the
reviewers' own scores; the organisation's agreement with the AI; and the admin's retry and
pinned re-run."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_api.access.deps import own_tenant
from hirevion_api.authz import Principal, requires
from hirevion_api.evaluation.schemas import (
    CalibrationResponse,
    CommunicationEvaluation,
    EvaluationAgreement,
    EvaluationBody,
    EvaluationCoding,
    EvaluationDimension,
    EvaluationEvidence,
    EvaluationFinding,
    EvaluationResponse,
    EvaluationState,
    EvaluationStatement,
    EvaluationVersions,
    FollowUpPerformance,
    HumanScoreBody,
    HumanScoreResponse,
    QuestionEvaluationBrief,
    QuestionEvaluationDetail,
    RerunQueued,
    RerunResponse,
    SkillEvaluation,
)
from hirevion_api.routing import api_router
from hirevion_core.access.audit import record
from hirevion_core.access.errors import Conflict, NotFound
from hirevion_core.access.scope import resource_scope
from hirevion_core.evaluation import calibration
from hirevion_core.evaluation.registry import DIMENSIONS
from hirevion_core.evaluation.runner import request_evaluation
from hirevion_core.evaluation.service import STALE_AFTER
from hirevion_core.interviews import assignment
from hirevion_core.models import Evaluation, Interview, InterviewQuestion, QuestionEvaluation

router = api_router(tags=["evaluation"])

Reads = Annotated[Principal, requires("reports.interview.view")]
Measures = Annotated[Principal, requires("reports.analytics.view")]
Administers = Annotated[Principal, requires("admin.ai.manage")]


def _reviewer_only(principal: Principal) -> UUID | None:
    """Reviewers (who can't see candidates) reach only the interviews they review."""
    return None if "candidates.view" in principal.permissions else principal.user_id


def _evidence(items: list[dict[str, Any]]) -> list[EvaluationEvidence]:
    return [EvaluationEvidence(**item) for item in items]


def _cited(item: dict[str, Any] | None) -> EvaluationStatement:
    item = item or {}
    return EvaluationStatement(
        summary=item.get("summary", ""),
        evidence=_evidence(item.get("evidence", [])),
        supported=bool(item.get("supported", False)),
    )


def _finding(item: dict[str, Any]) -> EvaluationFinding:
    return EvaluationFinding(
        text=item["text"],
        skill=item.get("skill"),
        evidence=_evidence(item.get("evidence", [])),
        supported=bool(item.get("supported")),
    )


def _brief(row: QuestionEvaluation, question: InterviewQuestion) -> QuestionEvaluationBrief:
    return QuestionEvaluationBrief(
        question_id=row.question_id,
        position=question.position,
        kind=row.kind,
        skill=row.skill,
        text=question.text,
        weight=float(row.weight),
        overall_score=float(row.overall_score),
        scores={name: float(d["score"]) for name, d in row.dimensions.items()},
        unsupported=list(row.unsupported),
        flags=list(row.flags),
    )


def _detail(
    row: QuestionEvaluation, question: InterviewQuestion, weights: dict[str, int]
) -> QuestionEvaluationDetail:
    return QuestionEvaluationDetail(
        **_brief(row, question).model_dump(),
        dimensions=[
            EvaluationDimension(
                dimension=name,
                weight=int(weights.get(name, 0)),
                score=float(row.dimensions[name]["score"]),
                raw_score=float(row.dimensions[name]["raw_score"]),
                supported=bool(row.dimensions[name]["supported"]),
                evidence=_evidence(row.dimensions[name]["evidence"]),
                rationale=row.dimensions[name].get("rationale", ""),
            )
            for name in DIMENSIONS
            if name in row.dimensions
        ],
        missing_concepts=list(row.missing_concepts),
        note=row.note,
        model=row.model,
    )


def _body(
    evaluation: Evaluation, rows: list[tuple[QuestionEvaluation, InterviewQuestion]]
) -> EvaluationBody:
    summary = evaluation.summary
    follow = summary.get("follow_up_performance", {})
    communication = summary.get("communication", {})
    pinned = evaluation.pinned
    return EvaluationBody(
        id=evaluation.id,
        sequence=evaluation.sequence,
        versions=EvaluationVersions(
            prompt=evaluation.prompt_version,
            synthesis_prompt=pinned.get("synthesis_prompt_version"),
            rubric=evaluation.rubric_version,
            evaluation=evaluation.evaluation_version,
            model=evaluation.model,
            models=list(pinned.get("models", [])),
        ),
        rubric_weights={k: int(v) for k, v in pinned.get("rubric", {}).get("weights", {}).items()},
        created_at=evaluation.created_at,
        completed_at=evaluation.completed_at,
        overall_score=float(evaluation.overall_score)
        if evaluation.overall_score is not None
        else None,
        communication=CommunicationEvaluation(
            score=communication.get("score"),
            evidence=_evidence(communication.get("evidence", [])),
            supported=bool(communication.get("supported", False)),
            summary=_cited(communication.get("summary")),
        ),
        skills=[
            SkillEvaluation(**{**item, "evidence": _evidence(item.get("evidence", []))})
            for item in evaluation.skills
        ],
        strengths=[_finding(item) for item in summary.get("strengths", [])],
        knowledge_gaps=[_finding(item) for item in summary.get("knowledge_gaps", [])],
        follow_up_performance=FollowUpPerformance(
            asked=int(follow.get("asked", 0)),
            mean=follow.get("mean"),
            main_mean=follow.get("main_mean"),
            delta=follow.get("delta"),
            summary=_cited(follow.get("summary")),
        ),
        coding=EvaluationCoding(
            **summary.get("coding", {"status": "pending", "score": None, "source": "sp-16"})
        ),
        flags=list(evaluation.flags),
        questions=[_brief(row, question) for row, question in rows],
    )


async def _latest(session: AsyncSession, interview_id: UUID, status: str) -> Evaluation | None:
    return await session.scalar(
        select(Evaluation)
        .where(
            Evaluation.interview_id == interview_id,
            Evaluation.kind == "initial",
            Evaluation.status == status,
        )
        .order_by(Evaluation.sequence.desc())
        .limit(1)
    )


async def _question_rows(
    session: AsyncSession, evaluation_id: UUID, question_id: UUID | None = None
) -> list[tuple[QuestionEvaluation, InterviewQuestion]]:
    statement = (
        select(QuestionEvaluation, InterviewQuestion)
        .join(InterviewQuestion, InterviewQuestion.id == QuestionEvaluation.question_id)
        .where(QuestionEvaluation.evaluation_id == evaluation_id)
        .order_by(InterviewQuestion.position)
    )
    if question_id is not None:
        statement = statement.where(QuestionEvaluation.question_id == question_id)
    return [(row[0], row[1]) for row in await session.execute(statement)]


@router.get("/interviews/{interview_id}/evaluation")
async def interview_evaluation(
    interview_id: UUID, request: Request, principal: Reads
) -> EvaluationResponse:
    """The final evaluation (PRD §70): the overall and skill scores, communication, strengths,
    knowledge gaps and follow-up performance, each with its verified evidence, and the
    questions' scores. It is `none` until the interview ends, `evaluating` while the evaluator
    runs and `failed` if it gave up."""
    async with own_tenant(request, principal) as session:
        scope = await resource_scope(session, principal.user_id)
        interview = await assignment.get_interview(
            session, interview_id, scope, reviewer_only=_reviewer_only(principal)
        )
        ready = await _latest(session, interview.id, "ready")
        if ready is not None:
            rows = await _question_rows(session, ready.id)
            return EvaluationResponse(
                interview_id=interview.id,
                interview_status=interview.status,
                state="ready",
                evaluation=_body(ready, rows),
            )
        failed = await _latest(session, interview.id, "failed")
        state: EvaluationState = "none"
        if interview.status == "evaluating":
            state = "evaluating"
        elif interview.status == "completed" and failed is not None:
            state = "failed"
        return EvaluationResponse(
            interview_id=interview.id,
            interview_status=interview.status,
            state=state,
            evaluation=None,
        )


@router.get("/interviews/{interview_id}/evaluation/questions/{question_id}")
async def question_evaluation(
    interview_id: UUID, question_id: UUID, request: Request, principal: Reads
) -> QuestionEvaluationDetail:
    """One question's eight dimensions, each with its score, the cap if it had no verified
    quote, its quotes with their transcript times, and the concepts the answer missed."""
    async with own_tenant(request, principal) as session:
        scope = await resource_scope(session, principal.user_id)
        interview = await assignment.get_interview(
            session, interview_id, scope, reviewer_only=_reviewer_only(principal)
        )
        ready = await _latest(session, interview.id, "ready")
        rows = await _question_rows(session, ready.id, question_id) if ready is not None else []
        if ready is None or not rows:
            raise NotFound("evaluation-not-found", "That question has no evaluation")
        row, question = rows[0]
        return _detail(row, question, ready.pinned.get("rubric", {}).get("weights", {}))


@router.put("/interviews/{interview_id}/questions/{question_id}/human-scores")
async def put_human_scores(
    interview_id: UUID,
    question_id: UUID,
    body: HumanScoreBody,
    request: Request,
    principal: Reads,
) -> HumanScoreResponse:
    """Records the signed-in reviewer's own dimension scores for a question (calibration);
    saving again replaces them. Other reviewers' scores are not shown."""
    async with own_tenant(request, principal) as session:
        scope = await resource_scope(session, principal.user_id)
        interview = await assignment.get_interview(
            session, interview_id, scope, reviewer_only=_reviewer_only(principal)
        )
        row = await calibration.record_human_scores(
            session,
            principal.actor(request),
            interview,
            question_id,
            body.dimensions,
            body.note,
        )
        return HumanScoreResponse(
            question_id=row.question_id,
            dimensions={k: float(v) for k, v in row.dimensions.items()},
            note=row.note,
            updated_at=row.updated_at,
        )


@router.get("/interviews/{interview_id}/human-scores")
async def my_human_scores(
    interview_id: UUID, request: Request, principal: Reads
) -> list[HumanScoreResponse]:
    """The signed-in reviewer's own scores for this interview's questions."""
    async with own_tenant(request, principal) as session:
        scope = await resource_scope(session, principal.user_id)
        interview = await assignment.get_interview(
            session, interview_id, scope, reviewer_only=_reviewer_only(principal)
        )
        rows = await calibration.own_scores(session, interview.id, principal.user_id)
        return [
            HumanScoreResponse(
                question_id=row.question_id,
                dimensions={k: float(v) for k, v in row.dimensions.items()},
                note=row.note,
                updated_at=row.updated_at,
            )
            for row in rows
        ]


@router.get("/evaluation/calibration")
async def evaluation_calibration(request: Request, principal: Measures) -> CalibrationResponse:
    """How closely reviewers' own scores agree with the AI's across the organisation: weighted
    kappa, Spearman, the mean gap and the AI's bias, overall and per dimension."""
    async with own_tenant(request, principal) as session:
        stats = await calibration.agreement(session)
    return CalibrationResponse(
        pairs=stats["pairs"],
        questions=stats["questions"],
        reviewers=stats["reviewers"],
        overall=EvaluationAgreement(**stats["overall"]),
        by_dimension={k: EvaluationAgreement(**v) for k, v in stats["by_dimension"].items()},
        bias=stats["bias"],
    )


def _rerun(row: Evaluation) -> RerunResponse:
    diff = row.diff
    return RerunResponse(
        id=row.id,
        sequence=row.sequence,
        status=row.status,
        created_at=row.created_at,
        completed_at=row.completed_at,
        requested_by=row.created_by,
        rerun_of=row.rerun_of,
        prompt_version=row.prompt_version,
        rubric_version=row.rubric_version,
        evaluation_version=row.evaluation_version,
        within_tolerance=bool(diff["within_tolerance"]) if diff else None,
        overall_score=float(row.overall_score) if row.overall_score is not None else None,
        diff=diff,
        error=row.error,
    )


@router.get("/interviews/{interview_id}/evaluation/reruns")
async def evaluation_reruns(
    interview_id: UUID, request: Request, principal: Administers
) -> list[RerunResponse]:
    """The pinned re-runs of this interview's evaluation and how far each moved."""
    async with own_tenant(request, principal) as session:
        scope = await resource_scope(session, principal.user_id)
        interview = await assignment.get_interview(session, interview_id, scope)
        rows = await session.scalars(
            select(Evaluation)
            .where(Evaluation.interview_id == interview.id, Evaluation.kind == "rerun")
            .order_by(Evaluation.sequence.desc())
        )
        return [_rerun(row) for row in rows.all()]


@router.post("/interviews/{interview_id}/evaluation/rerun", status_code=202)
async def request_rerun(
    interview_id: UUID, request: Request, principal: Administers
) -> RerunQueued:
    """Queues a pinned re-run of a finished evaluation (it reports its difference under
    `/evaluation/reruns`), or, for an interview whose evaluation never finished, a retry."""
    async with own_tenant(request, principal) as session:
        scope = await resource_scope(session, principal.user_id)
        interview: Interview = await assignment.get_interview(
            session, interview_id, scope, lock=True
        )
        ready = await _latest(session, interview.id, "ready")
        if ready is not None:
            action = "rerun"
        elif interview.status in ("completed", "evaluating"):
            running = await _latest(session, interview.id, "running")
            if running is not None and datetime.now(UTC) - running.updated_at < STALE_AFTER:
                raise Conflict("evaluation-in-progress", "The evaluation is still running")
            action = "evaluate"
        else:
            raise Conflict("not-evaluable", "Only an interview that has ended can be evaluated")
        await request_evaluation(
            session,
            interview.organization_id,
            interview.id,
            action=action,
            requested_by=principal.user_id,
        )
        await record(
            session,
            principal.actor(request),
            "evaluation.rerun_requested",
            "interview",
            interview.id,
            details={"action": action},
        )
    return RerunQueued(action=action)  # type: ignore[arg-type]
