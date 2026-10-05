"""The question library (PRD §22): each question a stable identity with immutable versions. An
edit writes the next version; nothing rewrites an old one, so interviews that used it keep it
(PRD §80). Only approved questions can be used by templates and interviews; AI drafts wait for a
recruiter (PRD §23)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.actor import Actor
from hirevion_core.access.audit import record
from hirevion_core.access.errors import Conflict, Invalid, NotFound
from hirevion_core.jobs.taxonomy import resolve_skills
from hirevion_core.models import Question, QuestionVersion
from hirevion_core.models.interview_config import (
    DIFFICULTIES,
    QUESTION_CATEGORIES,
    QUESTION_TYPES,
)

# PRD §45's coding languages.
CODING_LANGUAGES = ("python", "javascript", "typescript", "sql")
FOLLOW_UP_WHEN = ("strong", "partial", "weak")
CATEGORY_OF_TYPE = {
    "technical": "technical",
    "conceptual": "technical",
    "scenario": "technical",
    "problem_solving": "technical",
    "system_design": "system_design",
    "coding": "coding",
    "resume_based": "resume_based",
    "project_based": "resume_based",
}
TEXT_MIN, TEXT_MAX = 10, 4000


@dataclass(frozen=True, slots=True)
class QuestionFields:
    text: str
    skill_name: str
    difficulty: str
    type: str
    category: str | None = None
    """Defaults from the type (`CATEGORY_OF_TYPE`)."""
    topic: str | None = None
    expected_concepts: Sequence[str] = ()
    rubric: Sequence[dict[str, Any]] = ()
    time_limit_seconds: int | None = None
    follow_up_rules: Sequence[dict[str, Any]] = ()
    coding: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class QuestionFilters:
    category: str | None = None
    type: str | None = None
    skill: str | None = None
    difficulty: str | None = None
    status: str | None = None
    """Archived questions only show when asked for."""
    query: str | None = None


@dataclass(frozen=True, slots=True)
class QuestionDetail:
    question: Question
    version: QuestionVersion


@dataclass(frozen=True, slots=True)
class _Clean:
    text: str
    skill_name: str
    difficulty: str
    type: str
    category: str
    topic: str | None
    expected_concepts: list[str]
    rubric: list[dict[str, Any]]
    time_limit_seconds: int | None
    follow_up_rules: list[dict[str, Any]]
    coding: dict[str, Any] | None = field(default=None)


def _check(fields: QuestionFields) -> _Clean:
    text = " ".join(fields.text.split()) if "\n" not in fields.text else fields.text.strip()
    if len(text) < TEXT_MIN:
        raise Invalid("text-too-short", "Write the question in full", field="text")
    if len(text) > TEXT_MAX:
        raise Invalid("too-long", f"Use at most {TEXT_MAX} characters", field="text")
    skill = " ".join(fields.skill_name.split())
    if not skill or len(skill) > 100:
        raise Invalid("skill-required", "Name the skill it tests", field="skill_name")
    if fields.type not in QUESTION_TYPES:
        raise Invalid("invalid-type", "Choose a question type", field="type")
    if fields.difficulty not in DIFFICULTIES:
        raise Invalid("invalid-difficulty", "Choose easy, medium or hard", field="difficulty")
    category = fields.category or CATEGORY_OF_TYPE[fields.type]
    if category not in QUESTION_CATEGORIES:
        raise Invalid("invalid-category", "Choose a category", field="category")
    concepts = [c.strip()[:200] for c in fields.expected_concepts if c.strip()]
    if len(concepts) > 20:
        raise Invalid("too-many", "Up to 20 expected concepts", field="expected_concepts")
    rubric = []
    for item in fields.rubric:
        criterion = str(item.get("criterion", "")).strip()
        weight = item.get("weight")
        if not criterion or not isinstance(weight, int) or not 1 <= weight <= 100:
            raise Invalid(
                "invalid-rubric", "Each criterion needs a name and a weight", field="rubric"
            )
        rubric.append(
            {
                "criterion": criterion[:200],
                "weight": weight,
                "description": str(item.get("description", "")).strip()[:500],
            }
        )
    if rubric and sum(item["weight"] for item in rubric) != 100:
        raise Invalid("rubric-total", "The rubric's weights must add up to 100", field="rubric")
    limit = fields.time_limit_seconds
    if limit is not None and not 30 <= limit <= 3600:
        raise Invalid("invalid-time-limit", "Use 30 seconds to an hour", field="time_limit_seconds")
    rules = []
    for rule in fields.follow_up_rules:
        when, prompt = rule.get("when"), str(rule.get("prompt", "")).strip()
        if when not in FOLLOW_UP_WHEN or not prompt:
            raise Invalid(
                "invalid-rule",
                "Follow-ups apply to a strong, partial or weak answer",
                field="follow_up_rules",
            )
        rules.append({"when": when, "prompt": prompt[:500]})
    coding = None
    if fields.type == "coding" or fields.coding:
        given = fields.coding or {}
        languages = [str(lang).lower() for lang in given.get("languages", ["python"])]
        if not languages or any(lang not in CODING_LANGUAGES for lang in languages):
            raise Invalid(
                "invalid-language", "Use Python, JavaScript, TypeScript or SQL", field="coding"
            )
        starters = given.get("starter_code") or {}
        coding = {
            "languages": languages,
            "starter_code": {
                str(lang): str(code)[:20_000]
                for lang, code in starters.items()
                if lang in languages
            },
        }
    topic = (fields.topic or "").strip()[:100] or None
    return _Clean(
        text,
        skill,
        fields.difficulty,
        fields.type,
        category,
        topic,
        concepts,
        rubric,
        limit,
        rules,
        coding,
    )


async def _version(
    session: AsyncSession,
    actor: Actor,
    question: Question,
    number: int,
    clean: _Clean,
    generation: dict[str, Any] | None,
) -> QuestionVersion:
    [skill] = await resolve_skills(session, [clean.skill_name])
    version = QuestionVersion(
        organization_id=question.organization_id,
        question_id=question.id,
        version=number,
        text=clean.text,
        skill_name=skill.name if skill else clean.skill_name,
        skill_id=skill.skill_id if skill else None,
        topic=clean.topic,
        difficulty=clean.difficulty,
        type=clean.type,
        expected_concepts=clean.expected_concepts,
        rubric=clean.rubric,
        time_limit_seconds=clean.time_limit_seconds,
        follow_up_rules=clean.follow_up_rules,
        coding=clean.coding,
        generation=generation,
        created_by=actor.user_id,
    )
    session.add(version)
    await session.flush()
    return version


async def create_question(
    session: AsyncSession,
    actor: Actor,
    fields: QuestionFields,
    *,
    status: str = "approved",
    source: str = "manual",
    generation: dict[str, Any] | None = None,
) -> QuestionDetail:
    clean = _check(fields)
    approved = status == "approved"
    question = Question(
        organization_id=actor.organization_id,
        category=clean.category,
        status=status,
        source=source,
        current_version=1,
        created_by=actor.user_id,
        approved_by=actor.user_id if approved else None,
        approved_at=datetime.now(UTC) if approved else None,
    )
    session.add(question)
    await session.flush()
    version = await _version(session, actor, question, 1, clean, generation)
    await record(
        session,
        actor,
        "question.created",
        "question",
        question.id,
        details={"status": status, "source": source, "skill": version.skill_name},
    )
    return QuestionDetail(question, version)


async def _question(session: AsyncSession, question_id: UUID) -> Question:
    question = await session.get(Question, question_id)
    if question is None:
        raise NotFound("question-not-found", "No such question")
    return question


async def current_version(session: AsyncSession, question: Question) -> QuestionVersion:
    return await session.get_one(QuestionVersion, (question.id, question.current_version))


async def get_question(session: AsyncSession, question_id: UUID) -> QuestionDetail:
    question = await _question(session, question_id)
    return QuestionDetail(question, await current_version(session, question))


async def update_question(
    session: AsyncSession, actor: Actor, question_id: UUID, fields: QuestionFields
) -> QuestionDetail:
    """Writes the next version; the question keeps its status."""
    question = await _question(session, question_id)
    if question.status == "archived":
        raise Conflict("question-archived", "Restore the question before editing it")
    clean = _check(fields)
    number = question.current_version + 1
    version = await _version(session, actor, question, number, clean, None)
    question.current_version = number
    question.category = clean.category
    await session.flush()
    await record(
        session, actor, "question.updated", "question", question.id, details={"version": number}
    )
    return QuestionDetail(question, version)


async def approve(session: AsyncSession, actor: Actor, question_id: UUID) -> Question:
    question = await _question(session, question_id)
    if question.status == "archived":
        raise Conflict("question-archived", "Restore the question before approving it")
    if question.status != "approved":
        question.status = "approved"
        question.approved_by, question.approved_at = actor.user_id, datetime.now(UTC)
        await record(session, actor, "question.approved", "question", question.id)
    await session.flush()
    return question


async def archive(session: AsyncSession, actor: Actor, question_id: UUID) -> Question:
    question = await _question(session, question_id)
    if question.status != "archived":
        question.status = "archived"
        await record(session, actor, "question.archived", "question", question.id)
    await session.flush()
    return question


async def restore(session: AsyncSession, actor: Actor, question_id: UUID) -> Question:
    """An archived question comes back as a draft, to be approved again."""
    question = await _question(session, question_id)
    if question.status == "archived":
        question.status = "draft"
        await record(session, actor, "question.restored", "question", question.id)
    await session.flush()
    return question


async def list_versions(session: AsyncSession, question_id: UUID) -> list[QuestionVersion]:
    await _question(session, question_id)
    rows = await session.scalars(
        select(QuestionVersion)
        .where(QuestionVersion.question_id == question_id)
        .order_by(QuestionVersion.version)
    )
    return list(rows.all())


def _escaped(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def questions_statement(filters: QuestionFilters) -> Select[Question]:
    """The library's questions matching `filters`, by their current version."""
    current = and_(
        QuestionVersion.question_id == Question.id,
        QuestionVersion.version == Question.current_version,
    )
    statement = select(Question).join(QuestionVersion, current)
    if filters.status:
        statement = statement.where(Question.status == filters.status)
    else:
        statement = statement.where(Question.status != "archived")
    if filters.category:
        statement = statement.where(Question.category == filters.category)
    if filters.type:
        statement = statement.where(QuestionVersion.type == filters.type)
    if filters.difficulty:
        statement = statement.where(QuestionVersion.difficulty == filters.difficulty)
    if filters.skill and filters.skill.strip():
        statement = statement.where(
            func.lower(QuestionVersion.skill_name) == filters.skill.strip().lower()
        )
    if filters.query and filters.query.strip():
        words = [w for w in re.split(r"\s+", filters.query.strip()) if w][:8]
        statement = statement.where(
            and_(
                *(
                    or_(
                        QuestionVersion.text.ilike(f"%{_escaped(word)}%", escape="\\"),
                        QuestionVersion.topic.ilike(f"%{_escaped(word)}%", escape="\\"),
                    )
                    for word in words
                )
            )
        )
    return statement


async def describe(session: AsyncSession, rows: Sequence[Question]) -> list[QuestionDetail]:
    """Each question with its current version, in one query."""
    if not rows:
        return []
    versions = {
        version.question_id: version
        for version in (
            await session.scalars(
                select(QuestionVersion).where(
                    or_(
                        *(
                            and_(
                                QuestionVersion.question_id == q.id,
                                QuestionVersion.version == q.current_version,
                            )
                            for q in rows
                        )
                    )
                )
            )
        ).all()
    }
    return [QuestionDetail(question, versions[question.id]) for question in rows]


async def require_usable(session: AsyncSession, refs: Sequence[tuple[UUID, int]]) -> None:
    """Every (question, version) exists and the question is approved."""
    for question_id, number in refs:
        question = await session.get(Question, question_id)
        version = await session.get(QuestionVersion, (question_id, number))
        if question is None or version is None:
            raise Invalid(
                "question-not-found", "A chosen question doesn't exist", field="questions"
            )
        if question.status != "approved":
            raise Invalid(
                "question-not-approved",
                "Only approved questions can be used; approve the draft first",
                field="questions",
            )
