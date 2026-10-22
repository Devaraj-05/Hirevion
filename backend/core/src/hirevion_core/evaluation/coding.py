"""The coding evaluation (PRD §47; SP-16 inside SP-10; ADR-0033): after the interview, the code a
candidate submitted for each coding question is read by a model, never run.

One strong-tier call per coding question (`evaluation.coding`, prompt `evaluation-coding-v1`,
rubric `coding-v1`) scores seven criteria from 0 to 10: correctness of the logic, approach, edge
cases considered, time and space complexity (the model's estimate from reading, labelled as one),
code quality and readability. Each criterion cites quotes that must be in the code: they are
checked ignoring only spacing and carry their line numbers, and a criterion with none is capped at
`UNSUPPORTED_CAP` and flagged, as the answers' dimensions are. The question's score is the
criteria's mean by `WEIGHTS`, which are fixed and pinned with the evaluation.

The code reaches the model as JSON data under a prompt that says so; an instruction in a comment
is flagged for the reviewer and changes nothing else. Code that is empty is not sent anywhere.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from hirevion_core.ai.mock import respond_with
from hirevion_core.ai.types import AiContext, ChatMessage, LLMService
from hirevion_core.engine.guardrails import mentions_manipulation
from hirevion_core.evaluation import mockgrader, registry

PURPOSE = "evaluation.coding"
CRITERIA: tuple[str, ...] = (
    "correctness",
    "approach",
    "edge_cases",
    "time_complexity",
    "space_complexity",
    "code_quality",
    "readability",
)
COMPLEXITY = frozenset({"time_complexity", "space_complexity"})
WEIGHTS: dict[str, int] = {
    "correctness": 30,
    "approach": 15,
    "edge_cases": 15,
    "time_complexity": 10,
    "space_complexity": 5,
    "code_quality": 15,
    "readability": 10,
}
UNSUPPORTED_CAP = 5.0
CODE_MAX = 20_000
MIN_QUOTE = 6
MAX_QUOTES = 3
_TRIM = " \t\r\n`…"
Source = Literal["submitted", "time_limit", "closed", "snapshot", "none"]


def coding_rubric_version(base: str = registry.ACTIVE_CODING_RUBRIC) -> str:
    canonical = json.dumps(WEIGHTS, sort_keys=True)
    return f"{base}+w{hashlib.sha256(canonical.encode()).hexdigest()[:8]}"


@dataclass(frozen=True, slots=True)
class CodeEvidence:
    """A verified quote from the code and the lines it spans (1-based)."""

    quote: str
    line: int
    end_line: int

    def as_json(self) -> dict[str, Any]:
        return {"quote": self.quote, "line": self.line, "end_line": self.end_line}


def _flatten(code: str) -> tuple[str, list[int]]:
    """The code with every run of whitespace made one space, and each character's line."""
    chars: list[str] = []
    lines: list[int] = []
    line, pending = 1, False
    for ch in code:
        if ch == "\n":
            line += 1
        if ch.isspace():
            pending = bool(chars)
            continue
        if pending:
            chars.append(" ")
            lines.append(line)
            pending = False
        chars.append(ch)
        lines.append(line)
    return "".join(chars), lines


class CodeQuotes:
    """The code quotes are checked against: exact characters, any spacing."""

    def __init__(self, code: str) -> None:
        self._flat, self._lines = _flatten(code)

    def locate(self, quote: str) -> CodeEvidence | None:
        text = quote.strip(_TRIM)
        needle = " ".join(text.split())
        if len(needle) < MIN_QUOTE:
            return None
        start = self._flat.find(needle)
        if start < 0:
            return None
        return CodeEvidence(text, self._lines[start], self._lines[start + len(needle) - 1])

    def verify(self, quotes: Sequence[str], *, limit: int = MAX_QUOTES) -> list[CodeEvidence]:
        found: list[CodeEvidence] = []
        seen: set[str] = set()
        for quote in quotes:
            evidence = self.locate(quote)
            if evidence is None:
                continue
            key = " ".join(evidence.quote.split())
            if key in seen:
                continue
            seen.add(key)
            found.append(evidence)
            if len(found) == limit:
                break
        return found


class CriterionReply(BaseModel):
    score: float = Field(ge=0, le=10)
    quotes: list[str] = Field(default_factory=list, max_length=5)
    rationale: str = ""


class ComplexityReply(CriterionReply):
    estimate: str = Field("", max_length=60)


class CodingReply(BaseModel):
    correctness: CriterionReply
    approach: CriterionReply
    edge_cases: CriterionReply
    time_complexity: ComplexityReply
    space_complexity: ComplexityReply
    code_quality: CriterionReply
    readability: CriterionReply
    edge_cases_missed: list[str] = Field(default_factory=list, max_length=8)
    summary: str = ""


@dataclass(frozen=True, slots=True)
class CodingCase:
    """One coding question and the code that answers it (its final submission)."""

    question_id: str
    skill: str | None
    difficulty: str | None
    text: str
    language: str | None
    code: str
    submission_id: str | None
    source: Source
    expected_concepts: Sequence[str] = ()
    question_rubric: Sequence[Mapping[str, Any]] = ()


@dataclass(frozen=True, slots=True)
class CriterionScore:
    score: float
    raw_score: float
    supported: bool
    evidence: list[CodeEvidence]
    rationale: str
    estimate: str | None = None

    def as_json(self, name: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "score": self.score,
            "raw_score": self.raw_score,
            "supported": self.supported,
            "evidence": [item.as_json() for item in self.evidence],
            "rationale": self.rationale,
        }
        if name in COMPLEXITY:
            body |= {"estimate": self.estimate or None, "estimated": True}
        return body


@dataclass(frozen=True, slots=True)
class CodingScore:
    question_id: str
    skill: str | None
    language: str | None
    submission_id: str | None
    source: Source
    status: Literal["scored", "no_code"]
    overall: float
    criteria: dict[str, CriterionScore]
    prompt_version: str
    rubric_version: str
    summary: str = ""
    edge_cases_missed: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    model: str | None = None
    input_digest: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "skill": self.skill,
            "language": self.language,
            "submission_id": self.submission_id,
            "source": self.source,
            "status": self.status,
            "score": self.overall,
            "criteria": {name: c.as_json(name) for name, c in self.criteria.items()},
            "summary": self.summary,
            "edge_cases_missed": self.edge_cases_missed,
            "flags": self.flags,
            "unsupported": self.unsupported,
            "model": self.model,
            "input_digest": self.input_digest,
        }


def build_request(case: CodingCase) -> dict[str, Any]:
    """What the model sees: data only, in a fixed shape (also what the input digest covers)."""
    return {
        "question": case.text,
        "skill": case.skill,
        "difficulty": case.difficulty,
        "language": case.language,
        "expected_concepts": list(case.expected_concepts),
        "question_rubric": [dict(item) for item in case.question_rubric],
        "code": case.code[:CODE_MAX],
        "truncated": len(case.code) > CODE_MAX,
    }


def _digest(request: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(request, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def weighted(scores: Mapping[str, float]) -> float:
    total = sum(WEIGHTS[c] for c in CRITERIA if c in scores)
    if total <= 0:
        return 0.0
    return sum(WEIGHTS[c] * scores[c] for c in CRITERIA if c in scores) / total


class CodingEvaluator:
    """Scores one coding question's code. The prompt and rubric default to the versions in force;
    a pinned re-run passes the names an evaluation recorded."""

    def __init__(
        self,
        llm: LLMService,
        *,
        prompt_version: str = registry.ACTIVE_CODING_PROMPT,
        prompt_text: str | None = None,
        rubric_base: str = registry.ACTIVE_CODING_RUBRIC,
        rubric_text: str | None = None,
        evaluation_version: str = registry.EVALUATION_VERSION,
    ) -> None:
        self._llm = llm
        self.prompt_version = prompt_version
        self.rubric_base = rubric_base
        self.rubric_version = coding_rubric_version(rubric_base)
        self.evaluation_version = evaluation_version
        self.system = registry.system_message(
            prompt_text if prompt_text is not None else registry.load_prompt(prompt_version),
            rubric_text if rubric_text is not None else registry.load_rubric(rubric_base),
        )

    async def evaluate(
        self, organization_id: UUID, case: CodingCase, *, refs: Mapping[str, str]
    ) -> CodingScore:
        """Raises the provider layer's errors as they are; the caller decides what to retry."""
        flags = [] if case.source == "submitted" else [f"code_{case.source}"]
        if not case.code.strip():
            return CodingScore(
                question_id=case.question_id,
                skill=case.skill,
                language=case.language,
                submission_id=case.submission_id,
                source=case.source,
                status="no_code",
                overall=0.0,
                criteria={},
                prompt_version=self.prompt_version,
                rubric_version=self.rubric_version,
                flags=[*flags, "coding_not_answered"],
            )
        request = build_request(case)
        input_digest = _digest(request)
        messages: list[ChatMessage] = [
            {"role": "system", "content": self.system},
            {"role": "user", "content": json.dumps(request, ensure_ascii=False)},
        ]
        context = AiContext(
            organization_id=organization_id,
            purpose=PURPOSE,
            prompt_version=self.prompt_version,
            rubric_version=self.rubric_version,
            evaluation_version=self.evaluation_version,
            input_refs={**refs, "question": case.question_id, "input_sha256": input_digest},
        )
        result = await self._llm.complete(context, messages, CodingReply, tier="strong")
        reply = result.value
        quotes = CodeQuotes(request["code"])
        criteria: dict[str, CriterionScore] = {}
        for name in CRITERIA:
            item: CriterionReply = getattr(reply, name)
            evidence = quotes.verify(item.quotes)
            supported = bool(evidence)
            score = item.score if supported else min(item.score, UNSUPPORTED_CAP)
            criteria[name] = CriterionScore(
                score=round(score, 1),
                raw_score=round(item.score, 1),
                supported=supported,
                evidence=evidence,
                rationale=" ".join(item.rationale.split())[:400],
                estimate=" ".join(item.estimate.split())[:40]
                if isinstance(item, ComplexityReply)
                else None,
            )
        unsupported = [name for name, c in criteria.items() if not c.supported]
        if unsupported:
            flags.append("coding_unsupported")
        if mentions_manipulation(case.code):
            flags.append("manipulation_attempt")
        return CodingScore(
            question_id=case.question_id,
            skill=case.skill,
            language=case.language,
            submission_id=case.submission_id,
            source=case.source,
            status="scored",
            overall=round(weighted({n: c.score for n, c in criteria.items()}), 2),
            criteria=criteria,
            prompt_version=self.prompt_version,
            rubric_version=self.rubric_version,
            summary=" ".join(reply.summary.split())[:600],
            edge_cases_missed=[
                " ".join(e.split())[:200] for e in reply.edge_cases_missed if e.strip()
            ],
            flags=flags,
            unsupported=unsupported,
            model=result.model,
            input_digest=input_digest,
        )


def coding_slot(scores: Sequence[CodingScore]) -> dict[str, Any]:
    """The evaluation's coding entry: each coding question's assessment and their mean (a
    question with no code counts as 0)."""
    if not scores:
        return {"status": "not_asked", "score": None, "questions": []}
    scored = any(s.status == "scored" for s in scores)
    return {
        "status": "scored" if scored else "no_code",
        "score": round(sum(s.overall for s in scores) / len(scores), 2),
        "prompt_version": scores[0].prompt_version,
        "rubric_version": scores[0].rubric_version,
        "weights": dict(WEIGHTS),
        "questions": [s.as_json() for s in scores],
    }


def _mock_reply(messages: Sequence[ChatMessage]) -> dict[str, Any]:
    return mockgrader.grade_coding(messages[0]["content"], json.loads(messages[-1]["content"]))


# The mock profile reads code deterministically, following the prompt as written (mockgrader).
respond_with(PURPOSE, _mock_reply)
