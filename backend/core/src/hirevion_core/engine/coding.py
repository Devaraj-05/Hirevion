"""CodingController (PRD §34, §45; SP-16, ADR-0033): when the coding question comes, which one,
and how it ends. The question is asked after the skill ladder with the code workspace and the
template's languages; the candidate types the answer in a text console and submits it. The code is
never run: it is stored and reviewed by the evaluator after the interview."""

from __future__ import annotations

from typing import Literal

from hirevion_core.engine.planner import pick_coding
from hirevion_core.engine.state import InterviewState, PoolQuestion

Ending = Literal["submitted", "time_limit", "closed"]


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

    def asked(self, state: InterviewState, question_id: str) -> None:
        state.coding.question_id = question_id

    def skip(self, state: InterviewState) -> None:
        state.coding.status = "skipped"

    def submitted(self, state: InterviewState) -> None:
        state.coding.submissions += 1
        self.finish(state, "submitted")

    def finish(self, state: InterviewState, how: Ending) -> None:
        if state.coding.status == "active":
            state.coding.status = "done"
            state.coding.ended = how
