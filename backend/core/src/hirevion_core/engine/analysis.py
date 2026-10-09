"""AnswerAnalyzer (PRD §38): correctness, completeness, depth, missing concepts and contradictions
for one answer, with a quality the follow-up rules act on.

The live analysis uses the fast model (`interview.analyze`, prompt `interview-analyze-v1`) within
a latency budget; when the model fails, times out or isn't configured, a deterministic heuristic
answers instead: how many expected concepts the answer names, how long it is, and how much it
hedges. The mock profile answers with the same heuristic, so CI interviews behave like real ones.
SP-10's evaluator scores the answers properly afterwards; this only steers the conversation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from hirevion_core.ai.mock import respond_with
from hirevion_core.ai.types import AiContext, AiError, ChatMessage, LLMService
from hirevion_core.engine.faq import STOPWORDS, terms
from hirevion_core.engine.state import AskedQuestion

log = logging.getLogger(__name__)

PROMPT_VERSION = "interview-analyze-v1"
PURPOSE = "interview.analyze"
BUDGET_SECONDS = 4.0
ANSWER_MAX = 6000
OFF_TOPIC_WORDS = 20
_PROMPT = (files("hirevion_core.engine") / "prompts" / f"{PROMPT_VERSION}.md").read_text(
    encoding="utf-8"
)
_HEDGES = re.compile(
    r"\b(i think|i guess|maybe|probably|not sure|i'?m not certain|kind of|sort of|i believe)\b",
    re.IGNORECASE,
)


class AnswerAnalysis(BaseModel):
    correctness: float = Field(ge=0, le=1)
    completeness: float = Field(ge=0, le=1)
    depth: float = Field(ge=0, le=1)
    missing_concepts: list[str] = Field(default_factory=list, max_length=10)
    contradictions: list[str] = Field(default_factory=list, max_length=5)
    quality: Literal["partial", "strong", "weak", "no_answer"]
    off_topic: bool = False
    manipulation: bool = False


@dataclass(frozen=True, slots=True)
class Analysed:
    analysis: AnswerAnalysis
    source: Literal["model", "heuristic"]
    model: str | None = None


def _covered(concept: str, answer_terms: set[str], folded_answer: str) -> bool:
    wanted = terms(concept)
    if not wanted:
        return concept.casefold() in folded_answer
    return len(wanted & answer_terms) >= max(1, (len(wanted) + 1) // 2)


def heuristic(
    question: str, answer: str, expected_concepts: Sequence[str], skill: str | None = None
) -> AnswerAnalysis:
    """A deterministic analysis from the words alone."""
    tokens = re.findall(r"[\w'+#.-]+", answer)
    count = len(tokens)
    if count < 3:
        return AnswerAnalysis(
            correctness=0,
            completeness=0,
            depth=0,
            missing_concepts=list(expected_concepts)[:10],
            quality="no_answer",
        )
    answer_terms = terms(answer)
    folded = answer.casefold()
    concepts = [c for c in expected_concepts if c.strip()]
    matched = [c for c in concepts if _covered(c, answer_terms, folded)]
    missing = [c for c in concepts if c not in matched]
    hedging = min(0.3, 0.1 * len(_HEDGES.findall(answer)))
    if concepts:
        coverage = len(matched) / len(concepts)
    else:
        topic = terms(question) | (terms(skill) if skill else set())
        overlap = len(topic & answer_terms) / max(1, len(topic))
        coverage = min(1.0, 0.4 * min(1.0, count / 40) + 0.6 * min(1.0, overlap * 2))
    length = min(1.0, count / 80)
    depth = round(max(0.0, min(1.0, length * (0.5 + 0.5 * coverage)) - hedging), 2)
    completeness = round(coverage, 2)
    correctness = round(max(0.0, coverage - hedging / 2), 2)
    relevant = terms(question) - STOPWORDS
    # Long enough to be about something else, and sharing nothing with the question: a short
    # vague answer is weak, not off-topic, and gets a clarification instead.
    off_topic = (
        count >= OFF_TOPIC_WORDS
        and not matched
        and bool(relevant)
        and not (relevant & answer_terms)
        and not (skill and terms(skill) & answer_terms)
    )
    if off_topic:
        quality: Literal["partial", "strong", "weak", "no_answer"] = "weak"
    elif coverage >= 0.75 and count >= 25:
        quality = "strong"
    elif coverage >= 0.3 and count >= 12:
        quality = "partial"
    else:
        quality = "weak"
    return AnswerAnalysis(
        correctness=correctness,
        completeness=completeness,
        depth=depth,
        missing_concepts=missing[:10],
        quality=quality,
        off_topic=off_topic,
    )


def _request(question: AskedQuestion, answer: str) -> str:
    return json.dumps(
        {
            "question": question.text,
            "skill": question.skill,
            "difficulty": question.difficulty,
            "expected_concepts": list(question.expected_concepts),
            "answer": answer[:ANSWER_MAX],
        },
        ensure_ascii=False,
    )


def _mock_answer(messages: Sequence[ChatMessage]) -> dict[str, Any]:
    request = json.loads(messages[-1]["content"])
    return heuristic(
        str(request.get("question") or ""),
        str(request.get("answer") or ""),
        [str(c) for c in request.get("expected_concepts") or []],
        request.get("skill"),
    ).model_dump()


respond_with(PURPOSE, _mock_answer)


class AnswerAnalyzer:
    def __init__(self, llm: LLMService | None, budget_seconds: float = BUDGET_SECONDS) -> None:
        self._llm = llm
        self._budget = budget_seconds

    async def analyze(
        self, organization_id: UUID, interview_id: UUID, question: AskedQuestion, answer: str
    ) -> Analysed:
        fallback = heuristic(question.text, answer, question.expected_concepts, question.skill)
        if self._llm is None or fallback.quality == "no_answer":
            return Analysed(fallback, "heuristic")
        context = AiContext(
            organization_id=organization_id,
            purpose=PURPOSE,
            prompt_version=PROMPT_VERSION,
            input_refs={"interview_id": str(interview_id), "question_id": question.id},
        )
        messages: list[ChatMessage] = [
            {"role": "system", "content": _PROMPT},
            {"role": "user", "content": _request(question, answer)},
        ]
        try:
            result = await asyncio.wait_for(
                self._llm.complete(context, messages, AnswerAnalysis, tier="fast"), self._budget
            )
        except (AiError, TimeoutError) as error:
            log.warning("Live answer analysis fell back to the heuristic: %s", error)
            return Analysed(fallback, "heuristic")
        analysis = result.value
        # The model's flag is a second opinion; the deterministic guard already ran.
        return Analysed(analysis, "model", result.model)
