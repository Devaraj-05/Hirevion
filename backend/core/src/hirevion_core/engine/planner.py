"""QuestionPlanner (PRD §34, §36): the pool of questions the interview may ask, each with its
source. The template's pinned questions come first, then a resume question per skill with
evidence, then approved library questions in an order seeded by the interview (so candidates
vary and a re-run repeats), and a generated question fills any gap when it's needed.

`pick()` takes the next question for a skill at a difficulty, nearest rung first.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from typing import Any

from hirevion_core.engine import phrasing
from hirevion_core.engine.context import InterviewContext, LibraryQuestion
from hirevion_core.engine.state import (
    RUNGS,
    InterviewState,
    PoolQuestion,
    ResumeHook,
    SkillState,
    Workspace,
)

RESUME_TYPES = frozenset({"resume_based", "project_based"})


# The desktop workspace each question type opens: the coding console (ADR-0033), and for a
# design question a plain-text notes pad (the `whiteboard` workspace; product-owner decision,
# 2026-11-15, ADR-0041). Other questions are answered by voice or the text box alone.
WORKSPACES: dict[str, Workspace] = {"coding": "code", "system_design": "whiteboard"}


def _from_library(question: LibraryQuestion, skill: str, source: str) -> PoolQuestion:
    coding = question.coding or {}
    return PoolQuestion(
        key=f"q:{question.question_id}:{question.version}",
        skill=skill,
        difficulty=question.difficulty,
        type=question.type,
        text=question.text,
        source="pinned" if source == "pinned" else "library",
        source_ref={"question_id": str(question.question_id), "version": question.version},
        topic=question.topic,
        expected_concepts=list(question.expected_concepts),
        rubric=[dict(r) for r in question.rubric],
        time_limit_seconds=question.time_limit_seconds,
        follow_up_rules=[dict(r) for r in question.follow_up_rules],
        workspace=WORKSPACES.get(question.type, "none"),
        languages=[str(lang) for lang in coding.get("languages") or []],
    )


def said(text: str) -> str:
    """A question's text as compared for repeats: case, spacing and the closing mark ignored.
    A library may hold the same question more than once, each copy with its own id (the owner's
    run of 2026-11-21 asked one of 13 copies ten times)."""
    return " ".join(text.casefold().split()).rstrip("?.! ")


def concept_key(concept: str | None) -> str | None:
    """A concept as compared for repeats: case, spacing and punctuation ignored (C8-10)."""
    if not concept:
        return None
    folded = re.sub(r"[^\w+#]+", " ", concept.casefold()).strip()
    return folded or None


def library_order(seed: int, question: LibraryQuestion) -> bytes:
    return hashlib.sha256(f"{seed}:{question.question_id}".encode()).digest()


def seed_for(interview_id: str) -> int:
    return int.from_bytes(hashlib.sha256(interview_id.encode()).digest()[:4], "big")


def pool_question(item: dict[str, Any]) -> PoolQuestion:
    """A question plan's item as a pool question (C8-10)."""
    kind = str(item.get("type") or "technical")
    return PoolQuestion(
        key=str(item["key"]),
        skill=str(item["skill"]),
        difficulty=str(item.get("difficulty") or "medium"),
        type=kind,
        text=str(item["text"]),
        source=item.get("source") or "generated",
        source_ref=dict(item.get("source_ref") or {}),
        topic=item.get("concept"),
        expected_concepts=[str(c) for c in item.get("expected_concepts") or []],
        rubric=[dict(r) for r in item.get("rubric") or []],
        time_limit_seconds=item.get("time_limit_seconds"),
        workspace=WORKSPACES.get(kind, "none"),
        languages=[str(lang) for lang in item.get("languages") or []],
        concept=item.get("concept"),
    )


def merge_plan(state: InterviewState, items: Sequence[dict[str, Any]], version: int) -> int:
    """Adds a newer plan's questions (a late plan, a top-up) to a running interview's pool,
    leaving out any it already holds by key, text or concept; returns how many were added."""
    keys = {q.key for q in state.pool}
    texts = {said(q.text) for q in state.pool}
    concepts = {key for q in state.pool if (key := concept_key(q.concept))}
    added = 0
    for entry in items:
        question = pool_question(entry)
        concept = concept_key(question.concept)
        if (
            question.key in keys
            or said(question.text) in texts
            or (concept and concept in concepts)
        ):
            continue
        state.pool.append(question)
        keys.add(question.key)
        texts.add(said(question.text))
        if concept:
            concepts.add(concept)
        added += 1
    state.plan_version = version
    return added


def fresh_count(state: InterviewState) -> int:
    """How many questions this interview could still ask, across its skills."""
    total = 0
    for skill in state.skills:
        unused = _unused(state, skill.name)
        total += sum(1 for q in unused if q.source == "pinned") + len(_ladder(unused))
    return total


class QuestionPlanner:
    def plan(
        self,
        context: InterviewContext,
        skills: Sequence[SkillState],
        hooks: Sequence[ResumeHook],
        seed: int,
    ) -> list[PoolQuestion]:
        names = {s.name.casefold(): s.name for s in skills}
        if context.plan:
            return self._from_plan(context, names)
        allowed = set(context.question_types)
        coding = context.coding
        languages = {str(lang).lower() for lang in coding.get("languages") or []}
        pool: list[PoolQuestion] = []
        pinned_keys = set()
        for question in context.pinned:
            pinned_keys.add((question.question_id, question.version))
            skill = names.get(question.skill_name.casefold(), question.skill_name)
            pool.append(_from_library(question, skill, "pinned"))
        resume_allowed = bool(context.policy.get("use_resume", True)) and (
            not allowed or bool(allowed & RESUME_TYPES)
        )
        if resume_allowed:
            for hook in hooks:
                kind = "project_based" if hook.field == "projects" else "resume_based"
                pool.append(
                    PoolQuestion(
                        key=f"resume:{hook.skill.casefold()}:{hook.field}:{hook.index}",
                        skill=hook.skill,
                        difficulty="medium",
                        type=kind if not allowed or kind in allowed else "resume_based",
                        text=phrasing.resume_question(hook),
                        source="resume",
                        source_ref={
                            "field": hook.field,
                            "index": hook.index,
                            "label": hook.label,
                            "quote": hook.quote,
                            "page": hook.page,
                            "section": hook.section,
                        },
                        topic=hook.label or None,
                    )
                )
        library = [q for q in context.library if (q.question_id, q.version) not in pinned_keys]
        for question in sorted(library, key=lambda q: library_order(seed, q)):
            if question.type == "coding":
                offered = {
                    str(lang).lower() for lang in (question.coding or {}).get("languages", [])
                }
                if coding.get("enabled") and (not languages or offered & languages):
                    _add_once(pool, _from_library(question, question.skill_name, "library"))
                continue
            if allowed and question.type not in allowed:
                continue
            known = names.get(question.skill_name.casefold())
            if known is not None:
                _add_once(pool, _from_library(question, known, "library"))
        return pool

    def _from_plan(self, context: InterviewContext, names: dict[str, str]) -> list[PoolQuestion]:
        """With prepared questions (C8-10): the template's pinned questions, then the plan's
        (its library and AI questions already checked to be distinct), and the coding question
        from the library as before."""
        pool = [
            _from_library(q, names.get(q.skill_name.casefold(), q.skill_name), "pinned")
            for q in context.pinned
        ]
        for entry in context.plan:
            planned = pool_question(entry)
            planned.skill = names.get(planned.skill.casefold(), planned.skill)
            _add_once(pool, planned)
        coding = context.coding
        languages = {str(lang).lower() for lang in coding.get("languages") or []}
        if coding.get("enabled"):
            pinned_keys = {(q.question_id, q.version) for q in context.pinned}
            for question in context.library:
                if question.type != "coding" or (question.question_id, question.version) in (
                    pinned_keys
                ):
                    continue
                offered = {
                    str(lang).lower() for lang in (question.coding or {}).get("languages", [])
                }
                if not languages or offered & languages:
                    _add_once(pool, _from_library(question, question.skill_name, "library"))
        return pool


def _add_once(pool: list[PoolQuestion], question: PoolQuestion) -> None:
    """Adds `question` unless the pool already holds its text: a library copy is left out only
    once a usable copy is in, so a copy the filters turn away never hides one."""
    if all(said(q.text) != said(question.text) for q in pool):
        pool.append(question)


def _unused(state: InterviewState, skill: str) -> list[PoolQuestion]:
    """The skill's questions not yet asked, leaving out any whose text or concept this interview
    has asked (C8-10: never the same question in other words; a checkpoint saved before the pool
    dropped copies may still hold them)."""
    folded = skill.casefold()
    asked = {said(q.text) for q in state.pool if q.used}
    concepts = {key for q in state.pool if q.used and (key := concept_key(q.concept))}
    return [
        q
        for q in state.pool
        if not q.used
        and q.type != "coding"
        and q.skill.casefold() == folded
        and said(q.text) not in asked
        and (concept_key(q.concept) is None or concept_key(q.concept) not in concepts)
    ]


def _template(question: PoolQuestion) -> bool:
    return question.source == "generated" and "template" in question.source_ref


def _generated_texts(state: InterviewState, skill: SkillState) -> set[str]:
    folded = skill.name.casefold()
    return {q.text for q in state.pool if _template(q) and q.skill.casefold() == folded}


def _templates(skill: SkillState, rung: str, start: int) -> list[tuple[str, int]]:
    """The rung's generated questions for `skill` with their template numbers, from `start`."""
    count = len(phrasing.GENERATED.get(rung) or phrasing.GENERATED["medium"])
    return [
        (phrasing.generated_question(skill.name, rung, start + k), (start + k) % count)
        for k in range(count)
    ]


def has_fresh(state: InterviewState, skill: SkillState) -> bool:
    """Whether `skill` has a question this interview hasn't asked, in its text or its concept.
    A generic template never counts: the owner's run of 2026-11-22 asked nine of them per skill,
    the same question in other words."""
    unused = _unused(state, skill.name)
    return any(q.source == "pinned" for q in unused) or bool(_ladder(unused))


def _ladder(unused: list[PoolQuestion]) -> list[PoolQuestion]:
    """The questions the difficulty ladder may take: the library's and the plan's. A resume hook
    only opens its skill; a second "tell me about it" would be the first in other words."""
    return [q for q in unused if q.source == "library" or q.source_ref.get("plan")]


def _generated(state: InterviewState, skill: SkillState, rung: str) -> PoolQuestion:
    """A generated question at `rung` not yet asked for `skill`, else at the nearest rung; once
    every one was asked, the rung's next in turn."""
    asked = _generated_texts(state, skill)
    number = len(asked)
    index = RUNGS.index(rung) if rung in RUNGS else 1
    by_distance = sorted(range(len(RUNGS)), key=lambda i: (abs(i - index), -i))
    found = next(
        (
            (RUNGS[i], text, template)
            for i in by_distance
            for text, template in _templates(skill, RUNGS[i], number + state.seed)
            if text not in asked
        ),
        None,
    )
    level, text, template = found or (rung, *_templates(skill, rung, number + state.seed)[0])
    return PoolQuestion(
        key=f"gen:{skill.name.casefold()}:{number}",
        skill=skill.name,
        difficulty=level,
        type="technical",
        text=text,
        source="generated",
        source_ref={"template": f"{level}-{template}"},
    )


def pick(state: InterviewState, skill: SkillState, rung: str) -> PoolQuestion | None:
    """The next question for `skill` at `rung`, marked used; None when the skill has nothing new
    to ask (C8-10, owner 2026-11-22: never repeat). In turn: an unused pinned question (whatever
    its rung); the resume question to open the skill; the library's or the plan's question at the
    rung, then the nearest rung (higher first); and only in an interview without a plan, one
    generic question for a skill that has nothing else."""
    unused = _unused(state, skill.name)
    choice = next((q for q in unused if q.source == "pinned"), None)
    if choice is None and skill.asked == 0:
        choice = next((q for q in unused if q.source == "resume"), None)
        if choice is not None and not choice.source_ref.get("plan"):
            choice.difficulty = rung
    if choice is None:
        index = RUNGS.index(rung) if rung in RUNGS else 1

        def distance(question: PoolQuestion) -> tuple[int, int]:
            at = RUNGS.index(question.difficulty) if question.difficulty in RUNGS else 1
            return abs(at - index), -at

        choice = min(_ladder(unused), key=distance, default=None)
    if choice is None:
        folded = skill.name.casefold()
        if state.plan_version or any(
            _template(q) and q.skill.casefold() == folded for q in state.pool
        ):
            return None
        choice = _generated(state, skill, rung)
        state.pool.append(choice)
    choice.used = True
    return choice


def pick_coding(state: InterviewState) -> PoolQuestion | None:
    """The coding question, or None when there is none to offer: the template's pinned one, then
    one at the level the recruiter chose when scheduling (C8-11; the plan's written one is at that
    level), then any."""
    coding = [q for q in state.pool if q.type == "coding" and not q.used]
    level = state.coding.difficulty
    choice = (
        next((q for q in coding if q.source == "pinned"), None)
        or next((q for q in coding if level and q.difficulty == level), None)
        or next(iter(coding), None)
    )
    if choice is not None:
        choice.used = True
        if not choice.languages:
            choice.languages = list(state.coding.languages)
    return choice
