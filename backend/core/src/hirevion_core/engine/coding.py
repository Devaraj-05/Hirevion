"""CodingController (PRD §34, §45): when the coding question comes and which one. SP-09 asks it
after the skill ladder, with the code workspace and the template's languages; SP-16 adds the
runs, submissions, tests and its evaluation."""

from __future__ import annotations

from hirevion_core.engine.planner import pick_coding
from hirevion_core.engine.state import InterviewState, PoolQuestion


class CodingController:
    def due(self, state: InterviewState) -> bool:
        return state.coding.enabled and state.coding.status in ("none", "pending")

    def start(self, state: InterviewState) -> PoolQuestion | None:
        """The coding question, now active; None (and the stage skipped) when there's none."""
        question = pick_coding(state)
        if question is None:
            state.coding.status = "skipped"
            return None
        state.coding.status = "active"
        state.coding.question_key = question.key
        return question

    def skip(self, state: InterviewState) -> None:
        state.coding.status = "skipped"

    def finish(self, state: InterviewState) -> None:
        if state.coding.status == "active":
            state.coding.status = "done"
