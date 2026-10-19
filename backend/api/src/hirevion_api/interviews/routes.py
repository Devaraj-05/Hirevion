"""The question library (PRD §22, §23), interview templates (PRD §21, §80) and the
organisation's interview defaults (PRD §9). Every edit writes a new version; AI-generated
questions arrive as drafts for a recruiter to approve."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_api.access.deps import idempotency_scope, own_tenant
from hirevion_api.authz import Principal, requires
from hirevion_api.idempotency import Idempotency, idempotency
from hirevion_api.interviews.schemas import (
    Category,
    Difficulty,
    GenerateRequest,
    GenerateResponse,
    InterviewDefaults,
    InterviewDefaultsUpdate,
    MatrixPreview,
    MatrixRowResponse,
    QuestionBody,
    QuestionCreate,
    QuestionResponse,
    QuestionStatus,
    QuestionType,
    QuestionVersionResponse,
    TemplateBody,
    TemplateCreate,
    TemplateResponse,
    TemplateSummary,
    TemplateVersionResponse,
)
from hirevion_api.pagination import Page, PageParams, page_params, paginate
from hirevion_api.problems import ProblemError
from hirevion_api.routing import api_router
from hirevion_core.access.errors import Refused
from hirevion_core.access.scope import resource_scope
from hirevion_core.ai import AiServices
from hirevion_core.ai.types import AiBudgetExceeded, AiError
from hirevion_core.candidates import candidates
from hirevion_core.interviews import generation, questions, templates
from hirevion_core.interviews.generation import GenerationRequest
from hirevion_core.interviews.questions import QuestionDetail, QuestionFields, QuestionFilters
from hirevion_core.interviews.templates import TemplateDetail, TemplateFields
from hirevion_core.jobs import jobs
from hirevion_core.models import InterviewTemplate, InterviewTemplateVersion, Question
from hirevion_core.models.interview_config import DIFFICULTIES

log = logging.getLogger(__name__)
router = api_router(tags=["interviews"])

ViewsQuestions = Annotated[Principal, requires("questions.view")]
ManagesQuestions = Annotated[Principal, requires("questions.manage")]
ViewsTemplates = Annotated[Principal, requires("interviews.templates.view")]
ManagesTemplates = Annotated[Principal, requires("interviews.templates.manage")]
ReadsDefaults = Annotated[
    Principal, requires("interviews.templates.view", "admin.organization.manage")
]
ManagesOrganization = Annotated[Principal, requires("admin.organization.manage")]
Idempotent = Annotated[Idempotency, Depends(idempotency)]
Pages = Annotated[PageParams, Depends(page_params)]


def _question(detail: QuestionDetail) -> QuestionResponse:
    q, v = detail.question, detail.version
    return QuestionResponse(
        id=q.id,
        category=q.category,  # type: ignore[arg-type]
        status=q.status,  # type: ignore[arg-type]
        source=q.source,  # type: ignore[arg-type]
        version=v.version,
        text=v.text,
        skill_name=v.skill_name,
        skill_id=v.skill_id,
        topic=v.topic,
        difficulty=v.difficulty,  # type: ignore[arg-type]
        type=v.type,  # type: ignore[arg-type]
        expected_concepts=v.expected_concepts,
        rubric=v.rubric,
        time_limit_seconds=v.time_limit_seconds,
        follow_up_rules=v.follow_up_rules,
        coding=v.coding,
        generation=_shown(v.generation),
        approved_at=q.approved_at,
        created_at=q.created_at,
        updated_at=q.updated_at,
    )


def _shown(generation: dict[str, Any] | None) -> dict[str, Any] | None:
    """How a draft was made, without the ids of the job and candidate it was made from: those
    belong to people who may not be allowed to see them."""
    if generation is None:
        return None
    inputs = dict(generation.get("inputs") or {})
    for private in ("job", "candidate"):
        inputs.pop(private, None)
    return {**generation, "inputs": inputs}


def _fields(body: QuestionBody) -> QuestionFields:
    return QuestionFields(
        text=body.text,
        skill_name=body.skill_name,
        difficulty=body.difficulty,
        type=body.type,
        category=body.category,
        topic=body.topic,
        expected_concepts=body.expected_concepts,
        rubric=[item.model_dump() for item in body.rubric],
        time_limit_seconds=body.time_limit_seconds,
        follow_up_rules=[item.model_dump() for item in body.follow_up_rules],
        coding=body.coding.model_dump() if body.coding else None,
    )


def _summary(detail: TemplateDetail) -> TemplateSummary:
    t, v = detail.template, detail.version
    return TemplateSummary(
        id=t.id,
        name=t.name,
        description=t.description,
        status=t.status,  # type: ignore[arg-type]
        version=v.version,
        duration_minutes=v.duration_minutes,
        question_count=v.question_count,
        proctoring_level=v.proctoring_level,  # type: ignore[arg-type]
        third_eye=v.third_eye,  # type: ignore[arg-type]
        coding=bool(v.coding.get("enabled")),
        updated_at=t.updated_at,
    )


def _template(detail: TemplateDetail) -> TemplateResponse:
    return TemplateResponse(
        **_summary(detail).model_dump(),
        current=TemplateVersionResponse.model_validate(detail.version),
    )


def _template_fields(body: TemplateBody) -> TemplateFields:
    sent = body.model_dump(exclude_unset=True, exclude_none=True)
    pinned = sent.pop("questions", None)
    return TemplateFields(
        **sent,
        questions=None
        if pinned is None
        else [(item["question_id"], item["version"]) for item in pinned],
    )


def _defaults(values: dict[str, Any]) -> InterviewDefaults:
    return InterviewDefaults(**values, proctoring_presets=templates.PROCTORING_PRESETS)


async def _reloaded_question(session: AsyncSession, question_id: UUID) -> QuestionResponse:
    """After a change: the database sets `updated_at`, so read the row again."""
    await session.flush()
    session.expire_all()
    return _question(await questions.get_question(session, question_id))


async def _reloaded_template(session: AsyncSession, template_id: UUID) -> TemplateResponse:
    await session.flush()
    session.expire_all()
    return _template(await templates.get_template(session, template_id))


def _ai(request: Request) -> AiServices:
    ai = getattr(request.app.state, "ai", None)
    if ai is None:
        raise ProblemError(
            503,
            "ai-unavailable",
            "AI unavailable",
            "This server has no AI service configured, so it can't write questions.",
        )
    return cast(AiServices, ai)


def _ai_failed(error: AiError) -> ProblemError:
    if isinstance(error, AiBudgetExceeded):
        return ProblemError(
            429,
            "ai-budget-exceeded",
            "AI budget spent",
            "This month's AI budget is spent; ask an admin to raise it.",
        )
    log.warning("Question generation failed: %s", error)
    return ProblemError(
        503,
        "ai-unavailable",
        "AI unavailable",
        "The AI service couldn't write questions just now. Try again shortly.",
    )


# The question library


@router.get("/questions")
async def list_questions(
    request: Request,
    principal: ViewsQuestions,
    page: Pages,
    category: Category | None = None,
    type: QuestionType | None = None,
    difficulty: Difficulty | None = None,
    status: QuestionStatus | None = None,
    skill: Annotated[str | None, Query(max_length=100)] = None,
    q: Annotated[str | None, Query(max_length=200, description="Words in the text or topic.")] = (
        None
    ),
) -> Page[QuestionResponse]:
    """The library, most recently changed first. Archived questions show only when asked for."""
    filters = QuestionFilters(
        category=category, type=type, skill=skill, difficulty=difficulty, status=status, query=q
    )
    async with own_tenant(request, principal) as session:
        rows, next_cursor = await paginate(
            session,
            questions.questions_statement(filters),
            [Question.updated_at, Question.id],
            page,
            descending=True,
        )
        details = await questions.describe(session, rows)
        return Page(items=[_question(d) for d in details], next_cursor=next_cursor)


@router.post("/questions", status_code=201)
async def create_question(
    body: QuestionCreate, request: Request, principal: ManagesQuestions, idem: Idempotent
) -> QuestionResponse:
    """Adds a question; it's approved for use unless saved as a draft."""
    async with own_tenant(request, principal) as session:

        async def create() -> QuestionResponse:
            detail = await questions.create_question(
                session, principal.actor(request), _fields(body), status=body.status
            )
            return _question(detail)

        return await idem.run(
            session, principal.organization_id, idempotency_scope(principal), create
        )


@router.post("/questions/generate")
async def generate_questions(
    body: GenerateRequest, request: Request, principal: ManagesQuestions, idem: Idempotent
) -> GenerateResponse:
    """Drafts questions with AI from the job, a candidate's work history, the skills, the level
    and a template (PRD §23). They're saved as drafts: none is used until a recruiter approves
    it. A job or candidate must be one the caller may read. The AI call happens outside any
    database transaction, and a retry with the same `Idempotency-Key` costs nothing."""
    ai = _ai(request)
    actor = principal.actor(request)
    async with own_tenant(request, principal) as session:
        scope = await resource_scope(session, principal.user_id)
        if body.job_id is not None:
            if "jobs.view" not in principal.permissions:
                raise Refused("forbidden", "You don't have permission to read jobs")
            await jobs.require_in_scope(session, body.job_id, scope)
        if body.candidate_id is not None:
            if "candidates.view" not in principal.permissions:
                raise Refused("forbidden", "You don't have permission to read candidates")
            await candidates.get_candidate(session, body.candidate_id, scope)
        template = await _template_version(session, body.template_id) if body.template_id else None
        ask = GenerationRequest(
            skills=body.skills,
            count=body.count,
            experience_level=body.experience_level,
            job_id=body.job_id,
            candidate_id=body.candidate_id,
            template=template,
            types=body.types,
        )
        message, existing = await generation.gather(session, ask)
    refs = generation.refs_of(ask)

    async def generate() -> GenerateResponse:
        try:
            generated, model = await generation.ask(
                ai.llm, principal.organization_id, message, refs=refs
            )
        except AiError as error:
            raise _ai_failed(error) from error
        async with own_tenant(request, principal) as saving:
            result = await generation.save_drafts(
                saving,
                actor,
                generated,
                existing,
                model=model,
                refs=refs,
                limit=body.count,
                types=body.types,
            )
            return GenerateResponse(
                drafts=[_question(d) for d in result.drafts],
                skipped=result.skipped,
                model=result.model,
            )

    async with own_tenant(request, principal) as keeping:
        return await idem.run(
            keeping, principal.organization_id, idempotency_scope(principal), generate
        )


@router.get("/questions/{question_id}")
async def get_question(
    question_id: UUID, request: Request, principal: ViewsQuestions
) -> QuestionResponse:
    async with own_tenant(request, principal) as session:
        return _question(await questions.get_question(session, question_id))


@router.put("/questions/{question_id}")
async def update_question(
    question_id: UUID, body: QuestionBody, request: Request, principal: ManagesQuestions
) -> QuestionResponse:
    """Saves the question as its next version; earlier versions stay as they were."""
    async with own_tenant(request, principal) as session:
        await questions.update_question(
            session, principal.actor(request), question_id, _fields(body)
        )
        return await _reloaded_question(session, question_id)


@router.get("/questions/{question_id}/versions")
async def question_versions(
    question_id: UUID, request: Request, principal: ViewsQuestions
) -> list[QuestionVersionResponse]:
    async with own_tenant(request, principal) as session:
        rows = await questions.list_versions(session, question_id)
        return [QuestionVersionResponse.model_validate(row) for row in rows]


@router.post("/questions/{question_id}/approve")
async def approve_question(
    question_id: UUID,
    request: Request,
    principal: ManagesQuestions,
    version: Annotated[
        int | None,
        Query(ge=1, description="The version the reviewer read; refused if it has changed."),
    ] = None,
) -> QuestionResponse:
    """Makes the question's current version usable in templates and interviews."""
    async with own_tenant(request, principal) as session:
        await questions.approve(session, principal.actor(request), question_id, version)
        return await _reloaded_question(session, question_id)


@router.post("/questions/{question_id}/archive")
async def archive_question(
    question_id: UUID, request: Request, principal: ManagesQuestions
) -> QuestionResponse:
    """Hides the question from new use; templates that pinned it keep their version."""
    async with own_tenant(request, principal) as session:
        await questions.archive(session, principal.actor(request), question_id)
        return await _reloaded_question(session, question_id)


@router.post("/questions/{question_id}/restore")
async def restore_question(
    question_id: UUID, request: Request, principal: ManagesQuestions
) -> QuestionResponse:
    """Brings an archived question back as a draft, to be approved again."""
    async with own_tenant(request, principal) as session:
        await questions.restore(session, principal.actor(request), question_id)
        return await _reloaded_question(session, question_id)


# Interview templates


async def _template_version(session: AsyncSession, template_id: UUID) -> InterviewTemplateVersion:
    return (await templates.get_template(session, template_id)).version


@router.get("/interview-templates")
async def list_templates(
    request: Request,
    principal: ViewsTemplates,
    page: Pages,
    status: Annotated[str, Query(pattern="^(active|archived)$")] = "active",
    q: Annotated[str | None, Query(max_length=200, description="Part of the name.")] = None,
) -> Page[TemplateSummary]:
    """The templates, most recently changed first."""
    async with own_tenant(request, principal) as session:
        rows, next_cursor = await paginate(
            session,
            templates.templates_statement(status, q),
            [InterviewTemplate.updated_at, InterviewTemplate.id],
            page,
            descending=True,
        )
        details = await templates.describe(session, rows)
        return Page(items=[_summary(d) for d in details], next_cursor=next_cursor)


@router.post("/interview-templates", status_code=201)
async def create_template(
    body: TemplateCreate, request: Request, principal: ManagesTemplates, idem: Idempotent
) -> TemplateResponse:
    """A new template, starting from the organisation's interview defaults."""
    async with own_tenant(request, principal) as session:

        async def create() -> TemplateResponse:
            detail = await templates.create_template(
                session, principal.actor(request), _template_fields(body)
            )
            return _template(detail)

        return await idem.run(
            session, principal.organization_id, idempotency_scope(principal), create
        )


# Declared before /interview-templates/{template_id}/..., which can't take it but reads better.
@router.post("/interview-templates/skill-matrix")
async def preview_skill_matrix(
    body: MatrixPreview, request: Request, principal: ViewsTemplates
) -> list[MatrixRowResponse]:
    """The skill matrix for unsaved settings, while a template is being edited."""
    draft = InterviewTemplateVersion(
        question_count=body.question_count,
        skills=[item.model_dump() for item in body.skills],
        difficulty={d: body.difficulty.get(d, 0) for d in DIFFICULTIES},  # type: ignore[call-overload]
    )
    async with own_tenant(request, principal) as session:
        rows = await templates.skill_matrix(session, draft)
        return [MatrixRowResponse(**asdict(row)) for row in rows]


@router.get("/interview-templates/{template_id}")
async def get_template(
    template_id: UUID, request: Request, principal: ViewsTemplates
) -> TemplateResponse:
    async with own_tenant(request, principal) as session:
        return _template(await templates.get_template(session, template_id))


@router.patch("/interview-templates/{template_id}")
async def update_template(
    template_id: UUID, body: TemplateBody, request: Request, principal: ManagesTemplates
) -> TemplateResponse:
    """Saves the fields sent as the template's next version (PRD §80): interviews that pinned an
    earlier version keep it."""
    async with own_tenant(request, principal) as session:
        await templates.update_template(
            session, principal.actor(request), template_id, _template_fields(body)
        )
        return await _reloaded_template(session, template_id)


@router.get("/interview-templates/{template_id}/versions")
async def template_versions(
    template_id: UUID, request: Request, principal: ViewsTemplates
) -> list[TemplateVersionResponse]:
    async with own_tenant(request, principal) as session:
        rows = await templates.list_versions(session, template_id)
        return [TemplateVersionResponse.model_validate(row) for row in rows]


@router.get("/interview-templates/{template_id}/skill-matrix")
async def template_skill_matrix(
    template_id: UUID, request: Request, principal: ViewsTemplates
) -> list[MatrixRowResponse]:
    """How the current version's questions split across skills and difficulties, against the
    approved library questions available for each."""
    async with own_tenant(request, principal) as session:
        rows = await templates.skill_matrix(session, await _template_version(session, template_id))
        return [MatrixRowResponse(**asdict(row)) for row in rows]


@router.post("/interview-templates/{template_id}/archive")
async def archive_template(
    template_id: UUID, request: Request, principal: ManagesTemplates
) -> TemplateResponse:
    """Hides the template from new interviews; scheduled ones keep their version."""
    async with own_tenant(request, principal) as session:
        await templates.set_archived(session, principal.actor(request), template_id, True)
        return await _reloaded_template(session, template_id)


@router.post("/interview-templates/{template_id}/restore")
async def restore_template(
    template_id: UUID, request: Request, principal: ManagesTemplates
) -> TemplateResponse:
    async with own_tenant(request, principal) as session:
        await templates.set_archived(session, principal.actor(request), template_id, False)
        return await _reloaded_template(session, template_id)


# Organisation interview defaults


@router.get("/interview-defaults")
async def get_interview_defaults(request: Request, principal: ReadsDefaults) -> InterviewDefaults:
    """What new templates start from, and what each proctoring level turns on."""
    async with own_tenant(request, principal) as session:
        return _defaults(await templates.interview_defaults(session))


@router.put("/interview-defaults")
async def update_interview_defaults(
    body: InterviewDefaultsUpdate, request: Request, principal: ManagesOrganization
) -> InterviewDefaults:
    """Changes the defaults sent; existing templates keep their settings."""
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    async with own_tenant(request, principal) as session:
        saved = await templates.save_interview_defaults(session, principal.actor(request), changes)
        return _defaults(saved)
