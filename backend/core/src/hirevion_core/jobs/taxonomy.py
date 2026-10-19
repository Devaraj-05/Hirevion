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
    """The name without the punctuation around it. A dot that starts a name stays (".NET")."""
    text = " ".join(name.split()).rstrip(_WRAPPING)
    text = text.lstrip(_WRAPPING.replace(".", ""))
    while text.startswith(".") and not text[1:2].isalnum():
        text = text[1:]
    return " ".join(text.split())


async def resolve_skills(
    session: AsyncSession, names: Sequence[str]
) -> list[NormalisedSkill | None]:
    """Each name's skill, in one query: the taxonomy's spelling when it knows the skill, the
    name as written otherwise, and None for a blank name. One result per name, in order."""
    cleaned = [_clean(raw) for raw in names]
    lowered = {name.lower() for name in cleaned if name}
    known: dict[str, tuple[UUID, str]] = {}
    if lowered:
        by_name = select(func.lower(Skill.name), Skill.id, Skill.name, literal(0)).where(
            func.lower(Skill.name).in_(lowered)
        )
        by_alias = (
            select(func.lower(SkillAlias.alias), Skill.id, Skill.name, literal(1))
            .join(Skill, Skill.id == SkillAlias.skill_id)
            .where(func.lower(SkillAlias.alias).in_(lowered))
        )
        # A skill's own name beats another skill's alias of the same spelling.
        for key, skill_id, name, _rank in sorted(
            await session.execute(union_all(by_name, by_alias)), key=lambda row: row[3]
        ):
            known.setdefault(key, (skill_id, name))
    result: list[NormalisedSkill | None] = []
    for name in cleaned:
        if not name:
            result.append(None)
            continue
        skill_id, canonical = known.get(name.lower(), (None, name))
        result.append(NormalisedSkill(canonical, skill_id))
    return result


async def normalise_skills(session: AsyncSession, names: Sequence[str]) -> list[NormalisedSkill]:
    """The taxonomy's spelling for each known skill, the rest as written, in the given order,
    each skill once."""
    result: list[NormalisedSkill] = []
    seen: set[str] = set()
    for skill in await resolve_skills(session, names):
        if skill is None or skill.name.lower() in seen:
            continue
        seen.add(skill.name.lower())
        result.append(skill)
    return result


async def search_skills(session: AsyncSession, query: str, limit: int = 10) -> list[Skill]:
    """Skills whose name or an alias starts with `query`, then those most like it."""
    text = _clean(query).lower()
    if not text:
        return []
    alias_match = select(SkillAlias.skill_id).where(
        func.lower(SkillAlias.alias).startswith(text, autoescape=True)
    )
    prefix = or_(
        func.lower(Skill.name).startswith(text, autoescape=True), Skill.id.in_(alias_match)
    )
    likeness = func.similarity(func.lower(Skill.name), literal(text))
    rows = await session.scalars(
        select(Skill)
        .where(or_(prefix, likeness > 0.3))
        .order_by(prefix.desc(), likeness.desc(), Skill.name)
        .limit(limit)
    )
    return list(rows.all())
