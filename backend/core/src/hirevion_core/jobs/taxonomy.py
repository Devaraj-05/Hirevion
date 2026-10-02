"""The shared skills taxonomy (ADR-0015): one spelling per skill, whatever a job description or
resume called it, and a search for the skill picker. Skills it doesn't know stay as written."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.models import Skill, SkillAlias

# Punctuation that wraps a skill in running text ("(React)", "Python,"), not part of it: `+` and
# `#` stay, for C++ and C#.
_WRAPPING = " \t\n\"'()[]{},;:."


@dataclass(frozen=True, slots=True)
class NormalisedSkill:
    name: str
    skill_id: UUID | None


def _clean(name: str) -> str:
    return " ".join(name.strip(_WRAPPING).split())


async def normalise_skills(session: AsyncSession, names: Sequence[str]) -> list[NormalisedSkill]:
    """The taxonomy's spelling for each known skill, the rest as written, in the given order,
    each skill once."""
    cleaned = [name for name in (_clean(raw) for raw in names) if name]
    if not cleaned:
        return []
    lowered = {name.lower() for name in cleaned}
    by_name = select(func.lower(Skill.name), Skill.id, Skill.name).where(
        func.lower(Skill.name).in_(lowered)
    )
    by_alias = (
        select(func.lower(SkillAlias.alias), Skill.id, Skill.name)
        .join(Skill, Skill.id == SkillAlias.skill_id)
        .where(func.lower(SkillAlias.alias).in_(lowered))
    )
    known = {
        key: (skill_id, name)
        for key, skill_id, name in await session.execute(union_all(by_name, by_alias))
    }
    result: list[NormalisedSkill] = []
    seen: set[str] = set()
    for name in cleaned:
        skill_id, canonical = known.get(name.lower(), (None, name))
        if canonical.lower() in seen:
            continue
        seen.add(canonical.lower())
        result.append(NormalisedSkill(canonical, skill_id))
    return result


async def search_skills(session: AsyncSession, query: str, limit: int = 10) -> list[Skill]:
    """Skills whose name or an alias starts with `query`, then those most like it."""
    text = _clean(query).lower()
    if not text:
        return []
    alias_match = select(SkillAlias.skill_id).where(func.lower(SkillAlias.alias).startswith(text))
    prefix = or_(func.lower(Skill.name).startswith(text), Skill.id.in_(alias_match))
    likeness = func.similarity(func.lower(Skill.name), literal(text))
    rows = await session.scalars(
        select(Skill)
        .where(or_(prefix, likeness > 0.3))
        .order_by(prefix.desc(), likeness.desc(), Skill.name)
        .limit(limit)
    )
    return list(rows.all())
