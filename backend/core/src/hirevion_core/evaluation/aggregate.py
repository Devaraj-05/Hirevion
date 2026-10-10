"""Skill and final evaluations (PRD §70): the questions' scores combined by the rubric, and one
synthesis call for what numbers can't say (strengths, knowledge gaps, follow-up performance,
communication), every claim cited and verified like a score.

- A **skill's** score is the mean of its questions' dimension scores (a follow-up counts for half
  a main question), then weighted by the interview's rubric. Its evidence is the best verified
  quotes of its questions; a skill with no supported dimension is flagged.
- The **overall** score is the skills' mean by the weights the interview was planned with. A skill
  nothing was scored on is listed, not scored, and left out of the mean.
- **Communication** is the communication dimension across all the questions.
- **Coding** is a slot for SP-16 (§47), left pending.

These rules are `EVALUATION_VERSION`: changing the arithmetic means a new version.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from hirevion_core.ai.mock import respond_with
from hirevion_core.ai.types import AiContext, ChatMessage, LLMService
from hirevion_core.evaluation import mockgrader, registry
from hirevion_core.evaluation.evidence import Evidence, Quotable
from hirevion_core.evaluation.registry import DIMENSIONS, Rubric
from hirevion_core.evaluation.scoring import QuestionCase, QuestionScore, clock

SYNTHESIS_PURPOSE = "evaluation.synthesis"
GENERAL = "General"
SKILL_EVIDENCE = 5
ANSWER_EXCERPT = 1_200
CODING_SLOT: dict[str, Any] = {"status": "pending", "score": None, "source": "sp-16"}


@dataclass(frozen=True, slots=True)
class SkillPlan:
    """A skill the interview was planned around, with its weight."""

    name: str
    weight: float
    required: bool = False


@dataclass(frozen=True, slots=True)
class SkillScore:
    skill: str
    weight: float
    required: bool
    score: float | None
    questions: int
    dimensions: dict[str, float]
    evidence: list[Evidence]
    supported: bool

    def as_json(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "weight": self.weight,
            "required": self.required,
            "score": self.score,
            "questions": self.questions,
            "dimensions": self.dimensions,
            "evidence": [item.as_json() for item in self.evidence],
            "supported": self.supported,
        }


@dataclass(frozen=True, slots=True)
class CommunicationScore:
    score: float | None
    evidence: list[Evidence]
    supported: bool

    def as_json(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "evidence": [item.as_json() for item in self.evidence],
            "supported": self.supported,
        }


@dataclass(frozen=True, slots=True)
class Aggregate:
    overall: float | None
    skills: list[SkillScore]
    communication: CommunicationScore
    follow_ups: dict[str, Any]
    coding: dict[str, Any]
    flags: list[str] = field(default_factory=list)


def _mean(values: Sequence[tuple[float, float]]) -> float | None:
    total = sum(weight for _, weight in values)
    return sum(value * weight for value, weight in values) / total if total else None


def follow_up_stats(scores: Sequence[QuestionScore]) -> dict[str, Any]:
    follow = [s for s in scores if s.kind == "follow_up"]
    main = [s for s in scores if s.kind != "follow_up"]
    mean = round(sum(s.overall for s in follow) / len(follow), 2) if follow else None
    main_mean = round(sum(s.overall for s in main) / len(main), 2) if main else None
    delta = round(mean - main_mean, 2) if mean is not None and main_mean is not None else None
    return {"asked": len(follow), "mean": mean, "main_mean": main_mean, "delta": delta}


def _skill_score(
    name: str, plan: SkillPlan | None, scores: Sequence[QuestionScore], rubric: Rubric
) -> SkillScore:
    weight = plan.weight if plan else 1.0
    required = plan.required if plan else False
    if not scores:
        return SkillScore(name, weight, required, None, 0, {}, [], False)
    profile = {
        d: round(_mean([(s.dimensions[d].score, s.weight) for s in scores]) or 0.0, 2)
        for d in DIMENSIONS
    }
    evidence: list[Evidence] = []
    seen: set[str] = set()
    ranked = sorted(scores, key=lambda s: (-s.weight, -s.overall))
    by_weight = sorted(DIMENSIONS, key=lambda d: -rubric.weights[d])
    for score in ranked:
        for dimension in by_weight:
            for item in score.dimensions[dimension].evidence[:1]:
                if item.quote.lower() not in seen and len(evidence) < SKILL_EVIDENCE:
                    seen.add(item.quote.lower())
                    evidence.append(item)
    supported = any(d.supported for s in scores for d in s.dimensions.values())
    return SkillScore(
        name,
        weight,
        required,
        round(rubric.mean(profile), 2),
        len(scores),
        profile,
        evidence,
        supported,
    )


def aggregate(
    scores: Sequence[QuestionScore], plan: Sequence[SkillPlan], rubric: Rubric
) -> Aggregate:
    """Skill scores, communication and the overall score from the questions' scores."""
    by_skill: dict[str, list[QuestionScore]] = defaultdict(list)
    for score in scores:
        by_skill[score.skill or GENERAL].append(score)
    planned = {item.name.casefold(): item for item in plan}
    folded = {name.casefold(): name for name in by_skill}
    skills = [
        _skill_score(
            item.name, item, by_skill.get(folded.get(item.name.casefold(), ""), []), rubric
        )
        for item in plan
    ]
    planned_names = {item.name.casefold() for item in plan}
    skills += [
        _skill_score(name, planned.get(name.casefold()), by_skill[name], rubric)
        for name in by_skill
        if name.casefold() not in planned_names
    ]
    flags: list[str] = []
    if not scores:
        flags.append("no_scored_answers")
    for skill in skills:
        if skill.score is None and skill.required:
            flags.append(f"skill_not_assessed:{skill.skill}")
        elif skill.score is not None and not skill.supported:
            flags.append(f"unsupported_skill:{skill.skill}")
    overall = _mean([(s.score, s.weight) for s in skills if s.score is not None])
    communication_values = [(s.dimensions["communication"].score, s.weight) for s in scores]
    communication = _mean(communication_values)
    communication_evidence: list[Evidence] = []
    for score in sorted(scores, key=lambda s: -s.dimensions["communication"].score):
        communication_evidence += score.dimensions["communication"].evidence[:1]
    return Aggregate(
        overall=round(overall, 2) if overall is not None else None,
        skills=skills,
        communication=CommunicationScore(
            round(communication, 2) if communication is not None else None,
            communication_evidence[:3],
            bool(communication_evidence),
        ),
        follow_ups=follow_up_stats(scores),
        coding=dict(CODING_SLOT),
        flags=flags,
    )


class Finding(BaseModel):
    text: str
    skill: str | None = None
    quotes: list[str] = Field(default_factory=list, max_length=5)


class QuotedSummary(BaseModel):
    summary: str = ""
    quotes: list[str] = Field(default_factory=list, max_length=5)


class SynthesisReply(BaseModel):
    strengths: list[Finding] = Field(default_factory=list, max_length=8)
    knowledge_gaps: list[Finding] = Field(default_factory=list, max_length=8)
    follow_up_performance: QuotedSummary
    communication: QuotedSummary


@dataclass(frozen=True, slots=True)
class CitedFinding:
    text: str
    skill: str | None
    evidence: list[Evidence]
    supported: bool

    def as_json(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "skill": self.skill,
            "evidence": [item.as_json() for item in self.evidence],
            "supported": self.supported,
        }


@dataclass(frozen=True, slots=True)
class CitedSummary:
    summary: str
    evidence: list[Evidence]
    supported: bool

    def as_json(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "evidence": [item.as_json() for item in self.evidence],
            "supported": self.supported,
        }


@dataclass(frozen=True, slots=True)
class Synthesis:
    strengths: list[CitedFinding]
    gaps: list[CitedFinding]
    follow_up: CitedSummary
    communication: CitedSummary
    model: str | None

    def as_json(self) -> dict[str, Any]:
        return {
            "strengths": [f.as_json() for f in self.strengths],
            "knowledge_gaps": [f.as_json() for f in self.gaps],
            "follow_up_performance": self.follow_up.as_json(),
            "communication": self.communication.as_json(),
        }


EMPTY = CitedSummary("", [], False)


def _short(text: str, limit: int = 300) -> str:
    return " ".join(text.split())[:limit]


class Synthesizer:
    """The one call that writes what the numbers can't (strong tier), with evidence checked
    against every candidate turn of the interview."""

    def __init__(
        self,
        llm: LLMService,
        *,
        prompt_version: str = registry.ACTIVE_SYNTHESIS_PROMPT,
        prompt_text: str | None = None,
        evaluation_version: str = registry.EVALUATION_VERSION,
    ) -> None:
        self._llm = llm
        self.prompt_version = prompt_version
        self.evaluation_version = evaluation_version
        self.system = (
            prompt_text if prompt_text is not None else registry.load_prompt(prompt_version)
        ).strip()

    def _request(
        self,
        scores: Sequence[QuestionScore],
        cases: Sequence[QuestionCase],
        result: Aggregate,
    ) -> dict[str, Any]:
        by_id = {case.question_id: case for case in cases}
        questions = []
        for score in scores:
            case = by_id[score.question_id]
            turns, used = [], 0
            for turn in case.turns:
                text = turn.text[: max(0, ANSWER_EXCERPT - used)]
                if not text:
                    break
                used += len(text)
                turns.append({"n": turn.seq, "at": clock(turn.start_ms), "text": text})
            questions.append(
                {
                    "id": score.question_id,
                    "skill": score.skill,
                    "kind": score.kind,
                    "question": case.text,
                    "overall": score.overall,
                    "scores": score.scores(),
                    "missing_concepts": score.missing_concepts,
                    "answer_turns": turns,
                }
            )
        return {
            "skills": [
                {"skill": s.skill, "score": s.score, "questions": s.questions}
                for s in result.skills
            ],
            "follow_ups": result.follow_ups,
            "questions": questions,
        }

    async def synthesize(
        self,
        organization_id: UUID,
        scores: Sequence[QuestionScore],
        cases: Sequence[QuestionCase],
        result: Aggregate,
        rubric: Rubric,
        *,
        refs: Mapping[str, str],
    ) -> Synthesis:
        if not scores:
            return Synthesis([], [], EMPTY, EMPTY, None)
        request = self._request(scores, cases, result)
        messages: list[ChatMessage] = [
            {"role": "system", "content": self.system},
            {"role": "user", "content": json.dumps(request, ensure_ascii=False)},
        ]
        context = AiContext(
            organization_id=organization_id,
            purpose=SYNTHESIS_PURPOSE,
            prompt_version=self.prompt_version,
            rubric_version=rubric.version,
            evaluation_version=self.evaluation_version,
            input_refs=dict(refs),
        )
        reply = await self._llm.complete(context, messages, SynthesisReply, tier="strong")
        value = reply.value
        quotable = Quotable([turn for case in cases for turn in case.turns])

        def cite(findings: Sequence[Finding], *, keep_unsupported: bool) -> list[CitedFinding]:
            cited = []
            for finding in findings:
                evidence = quotable.verify(finding.quotes)
                if not evidence and not keep_unsupported:
                    continue
                cited.append(
                    CitedFinding(_short(finding.text), finding.skill, evidence, bool(evidence))
                )
            return cited

        def summarise(item: QuotedSummary) -> CitedSummary:
            evidence = quotable.verify(item.quotes)
            return CitedSummary(_short(item.summary, 500), evidence, bool(evidence))

        return Synthesis(
            strengths=cite(value.strengths, keep_unsupported=False)[:5],
            gaps=cite(value.knowledge_gaps, keep_unsupported=True)[:5],
            follow_up=summarise(value.follow_up_performance)
            if result.follow_ups["asked"]
            else EMPTY,
            communication=summarise(value.communication),
            model=reply.model,
        )


def _mock_synthesis(messages: Sequence[ChatMessage]) -> dict[str, Any]:
    return mockgrader.grade_synthesis(messages[0]["content"], json.loads(messages[-1]["content"]))


respond_with(SYNTHESIS_PURPOSE, _mock_synthesis)
