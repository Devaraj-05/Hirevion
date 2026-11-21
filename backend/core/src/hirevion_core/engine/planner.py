"""QuestionPlanner (PRD §34, §36): the pool of questions the interview may ask, each with its
source. The template's pinned questions come first, then a resume question per skill with
evidence, then approved library questions in an order seeded by the interview (so candidates
vary and a re-run repeats), and a generated question fills any gap when it's needed.

`pick()` takes the next question for a skill at a difficulty, nearest rung first.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

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


def _order(seed: int, question: LibraryQuestion) -> bytes:
    return hashlib.sha256(f"{seed}:{question.question_id}".encode()).digest()


def seed_for(interview_id: str) -> int:
    return int.from_bytes(hashlib.sha256(interview_id.encode()).digest()[:4], "big")


class QuestionPlanner:
    def plan(
        self,
        context: InterviewContext,
        skills: Sequence[SkillState],
        hooks: Sequence[ResumeHook],
        seed: int,
    ) -> list[PoolQuestion]:
        names = {s.name.casefold(): s.name for s in skills}
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
        for question in sorted(library, key=lambda q: _order(seed, q)):
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


def _add_once(pool: list[PoolQuestion], question: PoolQuestion) -> None:
    """Adds `question` unless the pool already holds its text: a library copy is left out only
    once a usable copy is in, so a copy the filters turn away never hides one."""
    if all(said(q.text) != said(question.text) for q in pool):
        pool.append(question)


def _unused(state: InterviewState, skill: str) -> list[PoolQuestion]:
    """The skill's questions not yet asked, leaving out any whose text this interview has asked
    (a checkpoint saved before the pool dropped copies may still hold them)."""
    folded = skill.casefold()
    asked = {said(q.text) for q in state.pool if q.used}
    return [
        q
        for q in state.pool
        if not q.used
        and q.type != "coding"
        and q.skill.casefold() == folded
        and said(q.text) not in asked
    ]


def _generated_texts(state: InterviewState, skill: SkillState) -> set[str]:
    folded = skill.name.casefold()
    return {q.text for q in state.pool if q.source == "generated" and q.skill.casefold() == folded}


def _templates(skill: SkillState, rung: str, start: int) -> list[tuple[str, int]]:
    """The rung's generated questions for `skill` with their template numbers, from `start`."""
    count = len(phrasing.GENERATED.get(rung) or phrasing.GENERATED["medium"])
    return [
        (phrasing.generated_question(skill.name, rung, start + k), (start + k) % count)
        for k in range(count)
    ]


def has_fresh(state: InterviewState, skill: SkillState) -> bool:
    """Whether `skill` has a question left that this interview hasn't asked: an unused one in
    the pool, or a generated one not yet used (an interview that runs its full length must not
    repeat itself, owner 2026-11-16)."""
    if _unused(state, skill.name):
        return True
    asked = _generated_texts(state, skill)
    return any(text not in asked for rung in RUNGS for text, _ in _templates(skill, rung, 0))


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


def pick(state: InterviewState, skill: SkillState, rung: str) -> PoolQuestion:
    """The next question for `skill` at `rung`: an unused pinned question first (whatever its
    rung), the resume question to open the skill, then the library at the rung or one either
    side, else a generated one at the rung (an easy question never follows a hard one just
    because the library ran out). The question is marked used."""
    unused = _unused(state, skill.name)
    choice = next((q for q in unused if q.source == "pinned"), None)
    if choice is None and skill.asked == 0:
        choice = next((q for q in unused if q.source == "resume"), None)
        if choice is not None:
            choice.difficulty = rung
    if choice is None:
        index = RUNGS.index(rung) if rung in RUNGS else 1
        by_distance = sorted(
            (i for i in range(len(RUNGS)) if abs(i - index) <= 1),
            key=lambda i: (abs(i - index), -i),
        )
        library = [q for q in unused if q.source == "library"]
        for candidate_index in by_distance:
            choice = next((q for q in library if q.difficulty == RUNGS[candidate_index]), None)
            if choice is not None:
                break
    if choice is None:
        choice = _generated(state, skill, rung)
        state.pool.append(choice)
    choice.used = True
    return choice


def pick_coding(state: InterviewState) -> PoolQuestion | None:
    """The coding question (pinned first), or None when the library has none to offer."""
    coding = [q for q in state.pool if q.type == "coding" and not q.used]
    choice = next((q for q in coding if q.source == "pinned"), None) or next(iter(coding), None)
    if choice is not None:
        choice.used = True
        if not choice.languages:
            choice.languages = list(state.coding.languages)
    return choice
