"""TimeController (PRD §40): the start, the deadline, the time left, each question's budget and
the coding time. When the plan no longer fits, follow-ups stop first, then the optional skills'
extra questions go (lowest weight first), then the covered required skills' extras; every
required skill that hasn't been covered keeps one question.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from hirevion_core.engine.state import AskedQuestion, InterviewState, SkillState

DEFAULT_BUDGET = 180
LONG_BUDGET = {"scenario": 300, "system_design": 300}
FOLLOW_UP_BUDGET = 90
RESERVE = 150
"""Held back for final questions and the close."""
FINAL_MINIMUM = 45
OVERRUN_GRACE = timedelta(seconds=10)
CODING_MINIMUM = 300


class TimeController:
    def remaining(self, state: InterviewState, now: datetime) -> int:
        seconds = state.clock.remaining(now)
        state.remaining_seconds = seconds
        return seconds

    def coding_seconds(self, state: InterviewState) -> int:
        coding = state.coding
        if not coding.enabled or coding.status not in ("none", "pending"):
            return 0
        return max(CODING_MINIMUM, coding.minutes * 60)

    def planned(self, state: InterviewState) -> int:
        """Seconds the rest of the plan needs, not counting the reserve."""
        return sum(s.remaining for s in state.skills) * DEFAULT_BUDGET + self.coding_seconds(state)

    def follow_up_fits(self, state: InterviewState, now: datetime) -> bool:
        spare = self.remaining(state, now) - RESERVE - self.planned(state)
        return spare >= FOLLOW_UP_BUDGET

    @staticmethod
    def _protected(skill: SkillState) -> bool:
        return skill.required and not skill.covered and skill.remaining <= 1

    def shrink(self, state: InterviewState, now: datetime) -> list[str]:
        """Lowers skills' targets until the plan fits the time left; returns those it cut."""
        available = self.remaining(state, now) - RESERVE
        cut: list[str] = []
        need = self.planned(state)
        while need > available:
            candidates = [s for s in state.skills if s.remaining > 0 and not self._protected(s)]
            if not candidates:
                break
            victim = min(
                candidates,
                key=lambda s: (s.required, s.weight, -s.remaining, s.name.casefold()),
            )
            victim.target -= 1
            cut.append(victim.name)
            need -= DEFAULT_BUDGET
        return cut

    def coding_limit(self, state: InterviewState, now: datetime) -> int | None:
        """The coding question's time limit: its minutes, within the time left; None when there
        isn't time for it."""
        spare = self.remaining(state, now) - RESERVE - sum(s.remaining for s in state.skills) * 60
        limit = min(state.coding.minutes * 60 or CODING_MINIMUM, spare)
        return limit if limit >= CODING_MINIMUM else None

    def overdue(self, question: AskedQuestion | None, now: datetime) -> bool:
        if question is None or not question.time_limit_seconds:
            return False
        limit = timedelta(seconds=question.time_limit_seconds) + OVERRUN_GRACE
        return now - question.asked_at > limit

    def late(self, question: AskedQuestion, now: datetime) -> bool:
        return self.overdue(question, now)
