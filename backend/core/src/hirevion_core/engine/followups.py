"""FollowUpGenerator (PRD §38): what to ask after an answer.

- strong → go deeper (the question's `strong` rule; otherwise the next question climbs a rung);
- partial → a targeted follow-up (the `partial` rule, or a question on the missing concepts);
- weak → a clarification (the `weak` rule, or a simpler way in);
- repeated weak answers → no follow-up: the orchestrator moves to another skill.

The decision is deterministic (`decide`). Only a targeted follow-up with no rule asks the fast
model to phrase it (`interview.follow_up`), and its text must pass the output guard; the template
is used otherwise.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from importlib.resources import files
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from hirevion_core.ai.mock import respond_with
from hirevion_core.ai.types import AiContext, AiError, ChatMessage, LLMService
from hirevion_core.engine import phrasing
from hirevion_core.engine.guardrails import safe_question
from hirevion_core.engine.state import AskedQuestion, InterviewState

log = logging.getLogger(__name__)

PROMPT_VERSION = "interview-follow-up-v1"
PURPOSE = "interview.follow_up"
BUDGET_SECONDS = 3.0
WEAK_STREAK = 2
_PROMPT = (files("hirevion_core.engine") / "prompts" / f"{PROMPT_VERSION}.md").read_text(
    encoding="utf-8"
)


class FollowUpText(BaseModel):
    question: str = Field(max_length=600)


@dataclass(frozen=True, slots=True)
class FollowUpPlan:
    kind: Literal["deeper", "targeted", "clarify"]
    text: str
    """The rule's prompt or the template: what's said when no model phrasing is used."""
    rule: bool
    missing: Sequence[str] = field(default_factory=tuple)

    @property
    def ask_model(self) -> bool:
        return self.kind == "targeted" and not self.rule


def _rule(question: AskedQuestion, when: str) -> str | None:
    for rule in question.follow_up_rules:
        if rule.get("when") == when and str(rule.get("prompt") or "").strip():
            return str(rule["prompt"]).strip()
    return None


def _mock_follow_up(messages: Sequence[ChatMessage]) -> dict[str, Any]:
    request = json.loads(messages[-1]["content"])
    return {"question": phrasing.partial_follow_up(request.get("missing_concepts") or [], 0)}


respond_with(PURPOSE, _mock_follow_up)


class FollowUpGenerator:
    def __init__(self, llm: LLMService | None = None, budget_seconds: float = BUDGET_SECONDS):
        self._llm = llm
        self._budget = budget_seconds

    def decide(
        self,
        state: InterviewState,
        question: AskedQuestion,
        quality: str,
        missing: Sequence[str],
        *,
        time_ok: bool,
    ) -> FollowUpPlan | None:
        """The follow-up `question`'s answer calls for, or None. At most one per main question,
        only with adaptive follow-ups on and the time to spare."""
        if not state.adaptive_follow_ups or question.kind != "main" or not time_ok:
            return None
        if question.follow_ups >= 1:
            return None
        topic = question.topic or question.skill or "this"
        seed = state.seed + question.position
        if quality == "strong":
            rule = _rule(question, "strong")
            return FollowUpPlan("deeper", rule, True) if rule else None
        if quality == "partial":
            rule = _rule(question, "partial")
            if rule:
                return FollowUpPlan("targeted", rule, True, tuple(missing))
            return FollowUpPlan(
                "targeted", phrasing.partial_follow_up(missing, seed), False, tuple(missing)
            )
        if quality == "weak":
            skill = state.skill(question.skill)
            if skill is not None and skill.weak_streak + 1 >= WEAK_STREAK:
                return None
            rule = _rule(question, "weak")
            return FollowUpPlan("clarify", rule or phrasing.clarification(topic, seed), bool(rule))
        return None

    async def phrase(
        self,
        organization_id: UUID,
        interview_id: UUID,
        question: AskedQuestion,
        answer: str,
        plan: FollowUpPlan,
    ) -> str:
        """The follow-up's wording: the model's when it asks for one and passes the guard."""
        if not plan.ask_model or self._llm is None:
            return plan.text
        context = AiContext(
            organization_id=organization_id,
            purpose=PURPOSE,
            prompt_version=PROMPT_VERSION,
            input_refs={"interview_id": str(interview_id), "question_id": question.id},
        )
        request = json.dumps(
            {
                "question": question.text,
                "answer": answer[:4000],
                "skill": question.skill,
                "missing_concepts": list(plan.missing)[:5],
            },
            ensure_ascii=False,
        )
        messages: list[ChatMessage] = [
            {"role": "system", "content": _PROMPT},
            {"role": "user", "content": request},
        ]
        try:
            result = await asyncio.wait_for(
                self._llm.complete(context, messages, FollowUpText, tier="fast"), self._budget
            )
        except (AiError, TimeoutError) as error:
            log.warning("Follow-up phrasing fell back to the template: %s", error)
            return plan.text
        return safe_question(result.value.question) or plan.text
