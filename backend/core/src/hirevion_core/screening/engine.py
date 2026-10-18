"""Screening one application (PRD §15 and §16): deterministic skill and experience scores, the AI
assessment of the rest, combined with the job's weights into a match score. Every factor keeps
its evidence. A result is reused when nothing it depends on changed: the resume, the job's
version, the configuration's version, the prompt and the model (master plan §6.7)."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.ai import AiServices
from hirevion_core.db.session import Database
from hirevion_core.hiring.workflow import sync_from_stage
from hirevion_core.models import (
    Application,
    ApplicationHistory,
    Candidate,
    CandidateSkill,
    Document,
    Job,
    JobSkill,
    ScreeningResult,
)
from hirevion_core.screening import config
from hirevion_core.screening.assess import PROMPT_VERSION, assess
from hirevion_core.screening.blind import blind_text
from hirevion_core.screening.factors import (
    CandidateSkillIn,
    JobSkillIn,
    SkillMatch,
    experience_score,
    skill_match,
)

YEARS_SHARE = 0.7  # the rest of the experience score is the AI's view of relevant roles
SCREENABLE = ("uploaded", "parsed")


def model_name(ai: AiServices) -> str:
    """The profile and model the AI layer will use for strong-tier calls."""
    settings = getattr(ai.llm, "settings", None)
    if settings is None:
        return "unknown"
    return f"{settings.profile}:{settings.llm_model_strong}"


def cache_key(document: Document | None, job: Job, version: str, model: str) -> str:
    parts = [
        document.sha256 if document and document.sha256 else "no-resume",
        str(job.id),
        str(job.version),
        version,
        PROMPT_VERSION,
        model,
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def job_text(job: Job, skills: Sequence[JobSkill]) -> str:
    """What the AI reads about the job."""

    def listed(title: str, items: Sequence[str]) -> list[str]:
        return [title, *(f"- {item}" for item in items)] if items else []

    lines = [f"Title: {job.title}"]
    for importance in ("required", "preferred", "optional"):
        names = [
            f"{s.name}" + (f" ({float(s.min_years):g}+ years)" if s.min_years else "")
            for s in skills
            if s.importance == importance
        ]
        if names:
            lines.append(f"{importance.capitalize()} skills: {', '.join(names)}")
    if job.experience_min is not None or job.experience_max is not None:
        low = float(job.experience_min or 0)
        high = f"{float(job.experience_max):g}" if job.experience_max is not None else "any"
        lines.append(f"Experience: {low:g} to {high} years")
    if job.location or job.work_model:
        lines.append(f"Location: {job.location or 'unspecified'} ({job.work_model or 'any'})")
    lines += listed("Responsibilities:", job.responsibilities)
    lines += listed("Qualifications:", job.qualifications)
    lines += listed("Domain:", job.domain)
    if job.description.strip():
        lines += ["Description:", job.description.strip()]
    return "\n".join(lines)


def cosine(a: Sequence[float] | None, b: Sequence[float] | None) -> float | None:
    if a is None or b is None or len(a) == 0 or len(a) != len(b):
        return None
    dot = sum(float(x) * float(y) for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(float(x) ** 2 for x in a)) * math.sqrt(sum(float(y) ** 2 for y in b))
    return round(dot / norm, 4) if norm else None


def _skill_quotes(profile: dict[str, Any], names: Sequence[str]) -> list[str]:
    wanted = {name.lower() for name in names}
    return [
        str(skill["quote"])
        for skill in profile.get("skills") or []
        if str(skill.get("name", "")).lower() in wanted and skill.get("quote")
    ][:5]


def _factors(
    match: SkillMatch,
    years: tuple[float, list[str]],
    ai: dict[str, dict[str, Any]],
    profile: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    years_score, notes = years
    roles = ai["roles"]
    experience = YEARS_SHARE * years_score + (1 - YEARS_SHARE) * roles["score"]
    return {
        "required_skills": {
            "score": round(match.required_score),
            "evidence": _skill_quotes(profile, match.matched_required),
            "matched": match.matched_required,
            "missing": match.missing_required,
            "supported": True,
        },
        "preferred_skills": {
            "score": round(match.preferred_score),
            "evidence": _skill_quotes(profile, match.matched_preferred),
            "matched": match.matched_preferred,
            "missing": match.missing_preferred,
            "supported": True,
        },
        "experience": {
            "score": round(experience),
            "evidence": roles["evidence"],
            "notes": notes,
            "supported": roles["supported"],
        },
        "projects": ai["projects"],
        "domain": ai["domain"],
        "education": ai["education"],
        "location": ai["location"],
    }


def weighted(factors: dict[str, dict[str, Any]], weights: dict[str, int]) -> int:
    total = sum(weight for weight in weights.values() if weight > 0)
    if total == 0:
        return 0
    score = sum(
        float(factors[name]["score"]) * weight for name, weight in weights.items() if weight > 0
    )
    return round(score / total)


async def record_stage(
    session: AsyncSession,
    application: Application,
    to_stage: str,
    action: str,
    *,
    actor_id: UUID | None = None,
    reason: str | None = None,
    score: int | None = None,
    rank: int | None = None,
    override: bool = False,
) -> None:
    moved = application.stage != to_stage
    session.add(
        ApplicationHistory(
            organization_id=application.organization_id,
            application_id=application.id,
            from_stage=application.stage,
            to_stage=to_stage,
            action=action,
            reason=reason,
            score=score,
            rank=rank,
            override=override,
            actor_id=actor_id,
        )
    )
    application.stage = to_stage
    # The hiring status (PRD §72) follows the stage, when the stage moves: an assignment that
    # records the same stage again must not rewrite a status that is already further along.
    if moved:
        await sync_from_stage(session, application, actor_id=actor_id, reason=reason)


async def screen_application(
    db: Database, ai: AiServices, organization_id: UUID, application_id: UUID
) -> ScreeningResult | None:
    """Screens one application (or reuses its result), links it and moves `parsed` → `screened`.
    AI outages raise, so the consumer retries."""
    model = model_name(ai)
    async with db.tenant(organization_id) as session:
        application = await session.get(Application, application_id)
        if application is None:
            return None
        job = await session.get_one(Job, application.job_id)
        candidate = await session.get_one(Candidate, application.candidate_id)
        document = (
            await session.get(Document, application.document_id)
            if application.document_id
            else None
        )
        settings = await config.effective(session, job.id)
        key = cache_key(document, job, f"{settings.source}:{settings.version}", model)
        cached = await session.scalar(
            select(ScreeningResult).where(
                ScreeningResult.cache_key == key, ScreeningResult.application_id == application.id
            )
        )
        if cached is not None:
            await _link(session, application, cached)
            return cached
        job_skills = list(
            (await session.scalars(select(JobSkill).where(JobSkill.job_id == job.id))).all()
        )
        candidate_skills = list(
            (
                await session.scalars(
                    select(CandidateSkill).where(CandidateSkill.candidate_id == candidate.id)
                )
            ).all()
        )
        text = (document.text if document else None) or ""
        resume = blind_text(text, candidate.profile) if settings.blind else text
        about_job = job_text(job, job_skills)
        profile = dict(candidate.profile)
        semantic = cosine(job.embedding, candidate.embedding)

    assessment = await assess(
        ai.llm, organization_id, about_job, resume, application_id=application_id
    )
    match = skill_match(
        [JobSkillIn(s.name, s.skill_id, s.importance, s.min_years) for s in job_skills],
        [CandidateSkillIn(s.name, s.skill_id, s.years) for s in candidate_skills],
    )
    total_years = profile.get("total_experience_years")
    years = experience_score(
        job.experience_min, job.experience_max, float(total_years) if total_years else None
    )
    factors = _factors(match, years, assessment.factors, profile)
    score = weighted(factors, settings.weights)
    knockouts = []
    if settings.knockouts.get("required_skills") and match.missing_required:
        knockouts.append(f"Missing required skills: {', '.join(match.missing_required)}")
    if (
        settings.knockouts.get("min_experience")
        and job.experience_min
        and years[0] < 100
        and total_years is not None
    ):
        knockouts.append(f"Below the minimum of {float(job.experience_min):g} years")
    missing = [f"Required skill: {name}" for name in match.missing_required] + [
        item for item in assessment.missing if item
    ]

    async with db.tenant(organization_id) as session:
        application = await session.get_one(Application, application_id)
        result = ScreeningResult(
            organization_id=organization_id,
            application_id=application.id,
            job_id=job.id,
            candidate_id=candidate.id,
            cache_key=key,
            job_version=job.version,
            config_version=settings.version,
            prompt_version=PROMPT_VERSION,
            model=assessment.model,
            score=score,
            factors=factors,
            skill_match={
                "required_score": round(match.required_score),
                "preferred_score": round(match.preferred_score),
                "matched_required": match.matched_required,
                "missing_required": match.missing_required,
                "short_on_years": match.short_on_years,
                "matched_preferred": match.matched_preferred,
                "missing_preferred": match.missing_preferred,
            },
            experience={
                "years": total_years,
                "minimum": float(job.experience_min) if job.experience_min is not None else None,
                "maximum": float(job.experience_max) if job.experience_max is not None else None,
                "score": factors["experience"]["score"],
                "notes": years[1],
            },
            strengths=assessment.strengths,
            concerns=assessment.concerns + years[1],
            missing=missing,
            knockouts=knockouts,
            semantic_similarity=semantic,
        )
        session.add(result)
        await session.flush()
        await _link(session, application, result)
        return result


async def _link(session: AsyncSession, application: Application, result: ScreeningResult) -> None:
    application.screening_result_id = result.id
    if application.stage in SCREENABLE:
        await record_stage(session, application, "screened", "screened", score=result.score)
    await session.flush()
