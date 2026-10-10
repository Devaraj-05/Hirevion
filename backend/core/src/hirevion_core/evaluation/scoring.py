"""The async `QuestionEvaluator` (PRD §44, master plan §6.9): after an interview ends, each
answered question is scored on the eight dimensions with one structured strong-tier call.

Every score cites quotes from the candidate's answer. The model's quotes are checked against the
stored transcript turns of that question (`evidence.Quotable`); what isn't there is dropped, and a
dimension left with no verified quote is capped at `UNSUPPORTED_CAP` and flagged, as screening
does (ADR-0016). The question's score is the mean of the eight dimensions weighted by the
interview's rubric.

The evaluator has no tools and its reply is schema-checked: the candidate's words reach it only
as JSON data under a prompt that says so, and nothing it returns can do more than set a bounded
number and some quotes that must be verified (docs/security/threat-model.md, SP-10).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from hirevion_core.ai.mock import respond_with
from hirevion_core.ai.types import AiContext, ChatMessage, LLMService
from hirevion_core.engine.guardrails import mentions_manipulation
from hirevion_core.evaluation import mockgrader, registry
from hirevion_core.evaluation.evidence import Evidence, Quotable, Turn
from hirevion_core.evaluation.registry import DIMENSIONS, Rubric

PURPOSE = "evaluation.question"
UNSUPPORTED_CAP = 5.0
# How much a question counts in its skill: a follow-up probes the same ground as its main
# question, so it counts for half.
QUESTION_WEIGHTS = {"main": 1.0, "follow_up": 0.5}
TURN_MAX = 4_000
ANSWER_MAX = 12_000
EARLIER_MAX = 1_500
SCORED_KINDS = tuple(QUESTION_WEIGHTS)


class DimensionReply(BaseModel):
    score: float = Field(ge=0, le=10)
    quotes: list[str] = Field(default_factory=list, max_length=5)
    rationale: str = ""


class QuestionReply(BaseModel):
    relevance: DimensionReply
    correctness: DimensionReply
    completeness: DimensionReply
    technical_depth: DimensionReply
    reasoning: DimensionReply
    clarity: DimensionReply
    communication: DimensionReply
    evidence: DimensionReply
    missing_concepts: list[str] = Field(default_factory=list, max_length=10)
    note: str = ""


@dataclass(frozen=True, slots=True)
class ParentContext:
    """For a follow-up: the main question and what the candidate said to it."""

    question: str
    answer: str


@dataclass(frozen=True, slots=True)
class QuestionCase:
    """Everything the evaluator needs about one answered question."""

    question_id: str
    kind: str
    skill: str | None
    difficulty: str | None
    text: str
    turns: Sequence[Turn]
    """The candidate's answer, as stored transcript turns; the only text quotes may come from."""
    expected_concepts: Sequence[str] = ()
    question_rubric: Sequence[Mapping[str, Any]] = ()
    parent: ParentContext | None = None
    flags: Sequence[str] = ()
    """Integrity signals the live guardrails raised (for a reviewer, never a verdict)."""
    late: bool = False


@dataclass(frozen=True, slots=True)
class DimensionScore:
    score: float
    """After the cap."""
    raw_score: float
    """As the model gave it."""
    supported: bool
    evidence: list[Evidence]
    rationale: str

    def as_json(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "raw_score": self.raw_score,
            "supported": self.supported,
            "evidence": [item.as_json() for item in self.evidence],
            "rationale": self.rationale,
        }


@dataclass(frozen=True, slots=True)
class QuestionScore:
    question_id: str
    kind: str
    skill: str | None
    weight: float
    dimensions: dict[str, DimensionScore]
    overall: float
    missing_concepts: list[str]
    note: str
    flags: list[str]
    model: str
    input_digest: str
    unsupported: list[str] = field(default_factory=list)

    def scores(self) -> dict[str, float]:
        return {name: dimension.score for name, dimension in self.dimensions.items()}


def clock(ms: int) -> str:
    seconds = ms // 1000
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def build_request(case: QuestionCase) -> dict[str, Any]:
    """What the model sees: data only, in a fixed shape (also what the input digest covers)."""
    total = 0
    answer_turns = []
    for turn in case.turns:
        text = turn.text[:TURN_MAX]
        if total + len(text) > ANSWER_MAX:
            break
        total += len(text)
        answer_turns.append({"n": turn.seq, "at": clock(turn.start_ms), "text": text})
    return {
        "question": case.text,
        "kind": case.kind,
        "skill": case.skill,
        "difficulty": case.difficulty,
        "expected_concepts": list(case.expected_concepts),
        "question_rubric": [dict(item) for item in case.question_rubric],
        "earlier_exchange": (
            {
                "question": case.parent.question,
                "answer": case.parent.answer[:EARLIER_MAX],
            }
            if case.parent is not None
            else None
        ),
        "answer_turns": answer_turns,
    }


def digest(request: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(request, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


class QuestionEvaluator:
    """Scores one question's answer. The prompt and rubric default to the versions in force;
    a pinned re-run passes the names an evaluation recorded."""

    def __init__(
        self,
        llm: LLMService,
        *,
        prompt_version: str = registry.ACTIVE_QUESTION_PROMPT,
        prompt_text: str | None = None,
        rubric_base: str = registry.ACTIVE_RUBRIC,
        rubric_text: str | None = None,
        evaluation_version: str = registry.EVALUATION_VERSION,
    ) -> None:
        self._llm = llm
        self.prompt_version = prompt_version
        self.evaluation_version = evaluation_version
        self.rubric_base = rubric_base
        self.system = registry.system_message(
            prompt_text if prompt_text is not None else registry.load_prompt(prompt_version),
            rubric_text if rubric_text is not None else registry.load_rubric(rubric_base),
        )

    async def evaluate(
        self,
        organization_id: UUID,
        case: QuestionCase,
        rubric: Rubric,
        *,
        refs: Mapping[str, str],
    ) -> QuestionScore:
        """Raises the provider layer's errors (`AiUnavailable`, `AiBudgetExceeded`, ...) as they
        are; the caller decides what to retry."""
        request = build_request(case)
        input_digest = digest(request)
        messages: list[ChatMessage] = [
            {"role": "system", "content": self.system},
            {"role": "user", "content": json.dumps(request, ensure_ascii=False)},
        ]
        context = AiContext(
            organization_id=organization_id,
            purpose=PURPOSE,
            prompt_version=self.prompt_version,
            rubric_version=rubric.version,
            evaluation_version=self.evaluation_version,
            input_refs={**refs, "question": case.question_id, "input_sha256": input_digest},
        )
        result = await self._llm.complete(context, messages, QuestionReply, tier="strong")
        reply = result.value
        quotable = Quotable(case.turns)
        dimensions: dict[str, DimensionScore] = {}
        for name in DIMENSIONS:
            item: DimensionReply = getattr(reply, name)
            evidence = quotable.verify(item.quotes, question_id=case.question_id)
            supported = bool(evidence)
            score = item.score if supported else min(item.score, UNSUPPORTED_CAP)
            dimensions[name] = DimensionScore(
                score=round(score, 1),
                raw_score=round(item.score, 1),
                supported=supported,
                evidence=evidence,
                rationale=" ".join(item.rationale.split())[:400],
            )
        flags = list(case.flags)
        if case.late:
            flags.append("late")
        if any(mentions_manipulation(turn.text) for turn in case.turns):
            flags.append("manipulation_attempt")
        return QuestionScore(
            question_id=case.question_id,
            kind=case.kind,
            skill=case.skill,
            weight=QUESTION_WEIGHTS.get(case.kind, 1.0),
            dimensions=dimensions,
            overall=round(rubric.mean({n: d.score for n, d in dimensions.items()}), 2),
            missing_concepts=[
                " ".join(c.split())[:200] for c in reply.missing_concepts if c.strip()
            ],
            note=" ".join(reply.note.split())[:600],
            flags=flags,
            model=result.model,
            input_digest=input_digest,
            unsupported=[name for name, d in dimensions.items() if not d.supported],
        )


def _mock_reply(messages: Sequence[ChatMessage]) -> dict[str, Any]:
    return mockgrader.grade_question(messages[0]["content"], json.loads(messages[-1]["content"]))


# The mock profile grades deterministically, following the prompt as written (mockgrader).
respond_with(PURPOSE, _mock_reply)
