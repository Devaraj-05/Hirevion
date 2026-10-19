"""AI question drafts (PRD §23): from the job, a candidate's work history, the skills, the
experience level, a template and the library, one structured AI call writes questions that are
saved as drafts. A recruiter edits and approves them before they become reusable; nothing the
AI writes is used directly. Candidates' names and contact details never reach the AI."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.resources import files
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.actor import Actor
from hirevion_core.access.audit import record
from hirevion_core.access.errors import Invalid
from hirevion_core.ai.types import AiContext, ChatMessage, LLMService
from hirevion_core.documents import pii
from hirevion_core.interviews.questions import QuestionDetail, QuestionFields, create_question
from hirevion_core.models import Candidate, Job, JobSkill, Question, QuestionVersion
from hirevion_core.models.interview_config import InterviewTemplateVersion

PROMPT_VERSION = "question-generate-v1"
PURPOSE = "questions.generate"
MAX_QUESTIONS = 10
LEVELS = ("junior", "mid", "senior", "lead")
EXISTING_SENT = 40
_PROMPT = (files("hirevion_core.interviews") / "prompts" / f"{PROMPT_VERSION}.md").read_text(
    encoding="utf-8"
)


class GeneratedRubric(BaseModel):
    criterion: str = Field(max_length=200)
    weight: int = Field(ge=1, le=100)


class GeneratedFollowUp(BaseModel):
    when: str = Field(pattern="^(strong|partial|weak)$")
    prompt: str = Field(max_length=500)


class GeneratedQuestion(BaseModel):
    text: str = Field(max_length=4000)
    skill_name: str = Field(max_length=100)
    topic: str | None = Field(None, max_length=100)
    difficulty: str = Field(pattern="^(easy|medium|hard)$")
    type: str = Field(
        pattern="^(technical|conceptual|scenario|system_design|coding|resume_based|"
        "project_based|problem_solving)$"
    )
    expected_concepts: list[str] = Field(default_factory=list, max_length=8)
    rubric: list[GeneratedRubric] = Field(default_factory=list, max_length=6)
    time_limit_seconds: int | None = Field(None, ge=30, le=3600)
    follow_up_rules: list[GeneratedFollowUp] = Field(default_factory=list, max_length=4)


class GeneratedQuestions(BaseModel):
    questions: list[GeneratedQuestion] = Field(default_factory=list, max_length=MAX_QUESTIONS)


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    skills: Sequence[str]
    count: int = 5
    experience_level: str = "mid"
    job_id: UUID | None = None
    candidate_id: UUID | None = None
    template: InterviewTemplateVersion | None = None
    types: Sequence[str] = ()


@dataclass(frozen=True, slots=True)
class GenerationResult:
    drafts: list[QuestionDetail]
    skipped: int
    """Questions left out: duplicates of the library, or ones that failed the library's checks."""
    model: str


def _fold(text: str) -> str:
    """Two questions that differ only in case, spacing or punctuation fold alike. Letters of any
    script count, and `+` and `#` do (C++ and C# are different questions)."""
    return re.sub(r"[^\w+#]+", " ", unicodedata.normalize("NFKC", text).lower()).strip()


_PERSONAL = (
    "email",
    "phone",
    "dob",
    "aadhaar",
    "pan",
    "vid",
    "passport",
    "voter_id",
    "bank_account",
)


def _scrub(text: str) -> str:
    """The text without contact details or identity numbers, wherever a resume put them."""
    out = text
    for match in sorted(pii.find(text), key=lambda m: m.start, reverse=True):
        if match.kind in _PERSONAL:
            out = out[: match.start] + "[removed]" + out[match.end :]
    return out


def _candidate_text(candidate: Candidate) -> str:
    """Work only: titles, companies, skills, projects. No name, contact or personal details,
    not even inside a project's description."""
    profile = candidate.profile or {}
    lines = []
    for position in profile.get("positions") or []:
        lines.append(
            " ".join(str(position.get(k) or "") for k in ("title", "company", "start", "end"))
        )
    skills = ", ".join(str(s.get("name")) for s in profile.get("skills") or [])
    if skills:
        lines.append(f"Skills: {skills}")
    for project in profile.get("projects") or []:
        lines.append(f"Project: {project.get('name')}: {project.get('description') or ''}")
    for item in profile.get("achievements") or []:
        lines.append(f"Achievement: {item.get('text')}")
    return _scrub("\n".join(line.strip() for line in lines if line.strip()))


def _job_text(job: Job, skills: Sequence[JobSkill]) -> str:
    lines = [f"Title: {job.title}"]
    lines += [f"{s.importance.capitalize()} skill: {s.name}" for s in skills]
    lines += [f"Responsibility: {item}" for item in job.responsibilities]
    if job.description.strip():
        lines.append(job.description.strip()[:6000])
    return "\n".join(lines)


async def _existing(session: AsyncSession, skills: Sequence[str]) -> list[str]:
    current = and_(
        QuestionVersion.question_id == Question.id,
        QuestionVersion.version == Question.current_version,
    )
    rows = await session.scalars(
        select(QuestionVersion.text)
        .select_from(Question)
        .join(QuestionVersion, current)
        .where(
            Question.status != "archived",
            func.lower(QuestionVersion.skill_name).in_([s.lower() for s in skills]),
        )
        .order_by(Question.updated_at.desc())
        .limit(200)
    )
    return list(rows.all())


def clean_skills(skills: Sequence[str]) -> list[str]:
    return [" ".join(s.split())[:100] for s in skills if s.strip()]


async def gather(session: AsyncSession, request: GenerationRequest) -> tuple[str, list[str]]:
    """The prompt's user message, and the library texts to de-duplicate against."""
    skills = clean_skills(request.skills)
    if not skills or len(skills) > 10:
        raise Invalid("skills-required", "Choose 1 to 10 skills", field="skills")
    if not 1 <= request.count <= MAX_QUESTIONS:
        raise Invalid("invalid-count", f"Ask for 1 to {MAX_QUESTIONS} questions", field="count")
    if request.experience_level not in LEVELS:
        raise Invalid("invalid-level", "Choose an experience level", field="experience_level")
    parts = [
        f"<skills>\n{', '.join(skills)}\n</skills>",
        f"<experience_level>\n{request.experience_level}\n</experience_level>",
        f"Write {request.count} questions.",
    ]
    if request.types:
        parts.append(f"Use these question types: {', '.join(request.types)}.")
    if request.job_id is not None:
        job = await session.get(Job, request.job_id)
        if job is None:
            raise Invalid("job-not-found", "No such job", field="job_id")
        job_skills = (
            await session.scalars(select(JobSkill).where(JobSkill.job_id == job.id))
        ).all()
        parts.append(f"<job>\n{_job_text(job, job_skills)}\n</job>")
    if request.candidate_id is not None:
        candidate = await session.get(Candidate, request.candidate_id)
        if candidate is None:
            raise Invalid("candidate-not-found", "No such candidate", field="candidate_id")
        parts.append(f"<candidate>\n{_candidate_text(candidate)}\n</candidate>")
    if request.template is not None:
        t = request.template
        mix = ", ".join(f"{k} {v}%" for k, v in t.difficulty.items())
        weights = ", ".join(f"{s['name']} {s['weight']}%" for s in t.skills)
        parts.append(
            f"<template>\nSkills: {weights}\nDifficulty: {mix}\n"
            f"Types: {', '.join(t.question_types)}\n</template>"
        )
    existing = await _existing(session, skills)
    if existing:
        listed = "\n".join(f"- {text[:300]}" for text in existing[:EXISTING_SENT])
        parts.append(f"<existing>\n{listed}\n</existing>")
    return "\n\n".join(parts), existing


async def ask(
    llm: LLMService, organization_id: UUID, message: str, *, refs: dict[str, str]
) -> tuple[GeneratedQuestions, str]:
    messages: list[ChatMessage] = [
        {"role": "system", "content": _PROMPT},
        {"role": "user", "content": message},
    ]
    context = AiContext(
        organization_id=organization_id,
        purpose=PURPOSE,
        prompt_version=PROMPT_VERSION,
        input_refs=refs,
    )
    result = await llm.complete(context, messages, GeneratedQuestions, tier="strong")
    return result.value, result.model


async def save_drafts(
    session: AsyncSession,
    actor: Actor,
    generated: GeneratedQuestions,
    existing: Sequence[str],
    *,
    model: str,
    refs: dict[str, str],
    limit: int = MAX_QUESTIONS,
    types: Sequence[str] = (),
) -> GenerationResult:
    """Saves the AI's questions as drafts: no more than `limit` (what was asked for), none of
    a type that was not asked for (when `types` is given), none already in the library."""
    seen = {_fold(text) for text in existing}
    drafts: list[QuestionDetail] = []
    skipped = max(0, len(generated.questions) - limit)
    for item in generated.questions[:limit]:
        if types and item.type not in types:
            skipped += 1
            continue
        key = _fold(item.text)
        if not key or key in seen:
            skipped += 1
            continue
        seen.add(key)
        fields = QuestionFields(
            text=item.text,
            skill_name=item.skill_name,
            difficulty=item.difficulty,
            type=item.type,
            topic=item.topic,
            expected_concepts=item.expected_concepts,
            rubric=[r.model_dump() for r in item.rubric]
            if sum(r.weight for r in item.rubric) == 100
            else [],
            time_limit_seconds=item.time_limit_seconds,
            follow_up_rules=[f.model_dump() for f in item.follow_up_rules],
            coding={"languages": ["python"]} if item.type == "coding" else None,
        )
        try:
            async with session.begin_nested():
                drafts.append(
                    await create_question(
                        session,
                        actor,
                        fields,
                        status="draft",
                        source="ai",
                        generation={
                            "model": model,
                            "prompt_version": PROMPT_VERSION,
                            "inputs": refs,
                        },
                    )
                )
        except Invalid:
            skipped += 1
    await record(
        session,
        actor,
        "questions.generated",
        "question",
        None,
        details={"drafts": len(drafts), "skipped": skipped, "inputs": refs, "model": model},
    )
    return GenerationResult(drafts, skipped, model)


def refs_of(request: GenerationRequest) -> dict[str, str]:
    refs = {"skills": ",".join(clean_skills(request.skills)), "level": request.experience_level}
    if request.job_id:
        refs["job"] = str(request.job_id)
    if request.candidate_id:
        refs["candidate"] = str(request.candidate_id)
    if request.template is not None:
        refs["template"] = f"{request.template.template_id}:{request.template.version}"
    return refs
