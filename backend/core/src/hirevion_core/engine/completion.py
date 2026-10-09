"""CompletionEvaluator (PRD §34, §37): whether the questions are done, and the coverage of the
skills, required ones first. A skill is covered once one of its main questions was answered."""

from __future__ import annotations

from typing import Any

from hirevion_core.engine.state import InterviewState


class CompletionEvaluator:
    def mains_left(self, state: InterviewState) -> bool:
        return any(s.remaining > 0 for s in state.skills)

    def coverage(self, state: InterviewState) -> list[dict[str, Any]]:
        return [
            {
                "skill": s.name,
                "required": s.required,
                "covered": s.covered,
                "asked": s.asked,
                "answered": s.answered,
                "planned": s.target,
                "dropped": s.dropped,
            }
            for s in sorted(state.skills, key=lambda s: (not s.required, -s.weight))
        ]

    def required_covered(self, state: InterviewState) -> bool:
        return all(s.covered for s in state.skills if s.required)

    def summary(self, state: InterviewState) -> dict[str, Any]:
        answered = [q for q in state.questions_asked if q.status == "answered"]
        return {
            "questions_asked": len(state.questions_asked),
            "questions_answered": len(answered),
            "required_covered": self.required_covered(state),
            "coverage": self.coverage(state),
            "stages": [mark.model_dump(mode="json") for mark in state.stages],
            "ended_reason": state.ended_reason,
        }
