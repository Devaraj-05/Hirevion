"""The deterministic screening factors: skill coverage and years of experience (PRD §15 "skill
matching", "experience matching"). Scores run from 0 to 100."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class JobSkillIn:
    name: str
    skill_id: UUID | None
    importance: str
    min_years: Decimal | None


@dataclass(frozen=True, slots=True)
class CandidateSkillIn:
    name: str
    skill_id: UUID | None
    years: Decimal | None


@dataclass(frozen=True, slots=True)
class SkillMatch:
    required_score: float
    preferred_score: float
    matched_required: list[str] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    short_on_years: list[str] = field(default_factory=list)
    matched_preferred: list[str] = field(default_factory=list)
    missing_preferred: list[str] = field(default_factory=list)


def skill_match(
    job_skills: Sequence[JobSkillIn], candidate_skills: Sequence[CandidateSkillIn]
) -> SkillMatch:
    """Required skills earn full credit, or half when the candidate has fewer years than the
    skill asks for; preferred skills count 1 and optional ones 0.5 towards the preferred score.
    A skill matches by taxonomy id, or by name ignoring case."""
    by_id = {skill.skill_id: skill for skill in candidate_skills if skill.skill_id}
    by_name = {skill.name.strip().lower(): skill for skill in candidate_skills}

    def found(skill: JobSkillIn) -> CandidateSkillIn | None:
        if skill.skill_id is not None and skill.skill_id in by_id:
            return by_id[skill.skill_id]
        return by_name.get(skill.name.strip().lower())

    required = [skill for skill in job_skills if skill.importance == "required"]
    matched, missing, short = [], [], []
    credit = 0.0
    for skill in required:
        held = found(skill)
        if held is None:
            missing.append(skill.name)
            continue
        matched.append(skill.name)
        if skill.min_years is not None and held.years is not None and held.years < skill.min_years:
            short.append(skill.name)
            credit += 0.5
        else:
            credit += 1.0
    required_score = 100.0 * credit / len(required) if required else 100.0

    extras = [skill for skill in job_skills if skill.importance in ("preferred", "optional")]
    possible = sum(1.0 if skill.importance == "preferred" else 0.5 for skill in extras)
    earned = 0.0
    matched_extra, missing_extra = [], []
    for skill in extras:
        if found(skill) is None:
            missing_extra.append(skill.name)
        else:
            matched_extra.append(skill.name)
            earned += 1.0 if skill.importance == "preferred" else 0.5
    preferred_score = 100.0 * earned / possible if possible else 100.0
    return SkillMatch(
        required_score,
        preferred_score,
        matched,
        missing,
        short,
        matched_extra,
        missing_extra,
    )


def _years(value: Decimal | float) -> str:
    number = float(value)
    return f"{number:g}"


def experience_score(
    minimum: Decimal | None, maximum: Decimal | None, candidate: float | None
) -> tuple[float, list[str]]:
    """Full marks at or above the minimum, linear below it. More than the maximum is never
    penalised; it only becomes a note for the recruiter."""
    notes: list[str] = []
    if minimum is None or minimum <= 0:
        score = 100.0
    elif candidate is None:
        return 50.0, ["Years of experience unclear"]
    elif candidate >= float(minimum):
        score = 100.0
    else:
        score = 100.0 * max(candidate, 0) / float(minimum)
        notes.append(f"{_years(candidate)} years against a minimum of {_years(minimum)}")
    if maximum is not None and candidate is not None and candidate > float(maximum):
        notes.append(f"{_years(candidate)} years, above the range of up to {_years(maximum)}")
    return score, notes
