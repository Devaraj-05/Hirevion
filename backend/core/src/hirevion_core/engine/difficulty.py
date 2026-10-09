"""DifficultyController (PRD §39): the next main question's rung for a skill. It starts from the
skill's ladder (the template's mix), climbs one rung after a strong answer and steps down one
after a weak one, between easy and hard. Coverage isn't its job: every skill still gets its
questions, whatever its rung."""

from __future__ import annotations

from hirevion_core.engine.state import RUNGS, SkillState


def _index(rung: str | None, default: int) -> int:
    return RUNGS.index(rung) if rung in RUNGS else default


class DifficultyController:
    def next_rung(self, skill: SkillState) -> str:
        position = min(skill.asked, len(skill.ladder) - 1) if skill.ladder else 0
        target = _index(skill.ladder[position] if skill.ladder else "medium", 1)
        if not skill.qualities or skill.rung is None:
            return RUNGS[target]
        last, previous = skill.qualities[-1], _index(skill.rung, target)
        if last == "strong":
            return RUNGS[min(len(RUNGS) - 1, max(target, previous + 1))]
        if last in ("weak", "no_answer"):
            return RUNGS[max(0, min(target, previous - 1))]
        return RUNGS[target]
