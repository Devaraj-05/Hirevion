"""SkillMatrixBuilder (PRD §34, §37): for each skill, its weight, whether it's required, how many
main questions it gets, its difficulty ladder (§39) and the resume evidence a question can start
from (§36)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from hirevion_core.engine.context import InterviewContext
from hirevion_core.engine.state import RUNGS, ResumeHook, SkillState
from hirevion_core.interviews.templates import allocate

SNIPPET_MAX = 140
_HOOK_FIELDS = ("projects", "positions", "achievements")


def snippet(text: str, limit: int = SNIPPET_MAX) -> str:
    """`text` on one line, cut at a word boundary to at most `limit` characters."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    cut = flat[:limit].rsplit(" ", 1)[0].rstrip(",;:-")
    return f"{cut}…"


def mentions(skill: str) -> re.Pattern[str]:
    """Matches `skill` as a whole term ("Go" not in "Google"; "C++" and ".NET" as written)."""
    return re.compile(rf"(?<![\w+#.]){re.escape(skill)}(?![\w+#])", re.IGNORECASE)


def ladder(count: int, mix: dict[str, int]) -> list[str]:
    shares = [mix.get(rung, 0) for rung in RUNGS]
    if count <= 0:
        return []
    if not any(shares):
        return ["medium"] * count
    split = allocate(count, shares)
    return [rung for rung, n in zip(RUNGS, split, strict=True) for _ in range(n)]


def _label(item: dict[str, Any]) -> str:
    if item.get("name"):
        return str(item["name"])
    parts = [str(item[k]) for k in ("title", "company") if item.get(k)]
    return " at ".join(parts)


def resume_hooks(profile: dict[str, Any], skills: Sequence[str]) -> list[ResumeHook]:
    """For each skill, the first verified resume item that mentions it: a project, a position or
    an achievement, else the skill's own entry when it carries a quote."""
    hooks: list[ResumeHook] = []
    for skill in skills:
        pattern = mentions(skill)
        hook: ResumeHook | None = None
        for field in _HOOK_FIELDS:
            for index, item in enumerate(profile.get(field) or []):
                if not isinstance(item, dict):
                    continue
                parts = [item.get(k) for k in ("quote", "description", "text", "name", "title")]
                if not any(isinstance(p, str) and pattern.search(p) for p in parts):
                    continue
                quote = str(item.get("quote") or item.get("description") or item.get("text"))
                hook = ResumeHook(
                    skill=skill,
                    field=field,
                    index=index,
                    label=_label(item),
                    quote=snippet(quote),
                    page=item.get("page") if isinstance(item.get("page"), int) else None,
                    section=item.get("section") if isinstance(item.get("section"), str) else None,
                )
                break
            if hook is not None:
                break
        if hook is None:
            for index, item in enumerate(profile.get("skills") or []):
                if (
                    isinstance(item, dict)
                    and str(item.get("name", "")).casefold() == skill.casefold()
                    and item.get("quote")
                ):
                    hook = ResumeHook(
                        skill=skill,
                        field="skills",
                        index=index,
                        label=str(item["name"]),
                        quote=snippet(str(item["quote"])),
                        page=item.get("page") if isinstance(item.get("page"), int) else None,
                        section=item.get("section")
                        if isinstance(item.get("section"), str)
                        else None,
                    )
                    break
        if hook is not None:
            hooks.append(hook)
    return hooks


class SkillMatrixBuilder:
    def build(self, context: InterviewContext) -> tuple[list[SkillState], list[ResumeHook]]:
        entries: list[tuple[str, int]] = []
        seen: set[str] = set()
        for item in context.template_skills:
            name = str(item.get("name", "")).strip()
            if name and name.casefold() not in seen:
                seen.add(name.casefold())
                entries.append((name, int(item.get("weight") or 0)))
        template_count = len(entries)
        required_jd = [s.name for s in context.job_skills if s.importance == "required"]
        if context.policy.get("use_jd", True):
            for name in required_jd:
                if name.casefold() not in seen:
                    seen.add(name.casefold())
                    entries.append((name, 0))
        for question in context.pinned:
            if question.type != "coding" and question.skill_name.casefold() not in seen:
                seen.add(question.skill_name.casefold())
                entries.append((question.skill_name, 0))

        counts = allocate(context.question_count, [w for _, w in entries[:template_count]])
        counts += [0] * (len(entries) - template_count)
        required_names = {n.casefold() for n in required_jd}
        has_jd = bool(context.job_skills)
        required = [
            (name.casefold() in required_names) if has_jd else index < template_count
            for index, (name, _) in enumerate(entries)
        ]
        pinned_by_skill: dict[str, int] = {}
        for question in context.pinned:
            if question.type != "coding":
                key = question.skill_name.casefold()
                pinned_by_skill[key] = pinned_by_skill.get(key, 0) + 1
        # Every required skill and every pinned question gets a slot, taken from the skill with
        # the most when there's one to spare.
        for index, (name, _) in enumerate(entries):
            wanted = max(1 if required[index] else 0, pinned_by_skill.get(name.casefold(), 0))
            while counts[index] < wanted:
                donor = max(
                    (i for i in range(len(entries)) if i != index and counts[i] > 1),
                    key=lambda i: (counts[i], -i),
                    default=None,
                )
                if donor is not None:
                    counts[donor] -= 1
                counts[index] += 1

        mix = context.difficulty_mix
        skills = [
            SkillState(
                name=name,
                weight=weight,
                required=required[index],
                target=counts[index],
                ladder=ladder(counts[index], mix),
            )
            for index, (name, weight) in enumerate(entries)
            if counts[index] > 0
        ]
        hooks = resume_hooks(context.profile, [s.name for s in skills]) if context.profile else []
        return skills, hooks
