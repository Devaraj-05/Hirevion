"""The AI part of screening (PRD §15 "LLM reasoning where useful"): one structured call scoring
the factors rules can't (relevant roles, projects, domain, education, location), each with
quotes from the resume. Quotes are checked against the resume; a factor whose evidence doesn't
check out is capped, because a score must have evidence (PRD §16). What the AI writes about
the candidate (strengths, concerns) is kept only if it speaks of the work: a sentence about
someone's gender, age, family, religion, caste or health is dropped, whatever the prompt said.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass
from importlib.resources import files
from typing import Any
from uuid import UUID

from pydantic import Field

from hirevion_core.ai.types import AiContext, ChatMessage, LLMService
from hirevion_core.documents.prompt_text import fence
from hirevion_core.documents.quotes import fold, verified
from hirevion_core.documents.trimmed import Trimmed

PROMPT_VERSION = "screening-assess-v1"
PURPOSE = "screening.assess"
UNSUPPORTED_CAP = 50
MAX_RESUME = 30_000
MAX_JOB = 12_000
# Factors that may be scored without quotes, when the job asks nothing of them (the caller says
# which: a job with no qualifications asks nothing of education, one with no place of location).
EVIDENCE_OPTIONAL = frozenset({"education", "location"})
AI_FACTORS = ("roles", "projects", "domain", "education", "location")
# Words about who a person is, not what they can do (PRD §3.2(1)). A comment containing one is
# not shown.
_PROTECTED = re.compile(
    r"\b(?:male|female|woman|women|boy|girl|gender|sex|young|younger|youth|elderly|"
    r"man(?!-)|men(?!-)|old(?:er)?\s+(?:candidate|applicant|person|worker)|"
    r"(?:too|rather|fairly|quite)\s+old|(?:his|her|their|candidate'?s)\s+age|"
    r"age\s*:|ages?d?\s+\d+|\d+\s*(?:years?|yrs?)\s+old|"
    r"married|unmarried|marital|marriage|pregnan\w*|maternity|wife|husband|spouse|"
    r"(?:has|have|having|her|his|their|two|three|young|small)\s+(?:\w+\s+)?(?:children|kids)|"
    r"famil(?:y|ies)\s+(?:commitments?|responsibilit\w+)|religio\w*|hindu|muslim|christian|sikh|"
    r"jain|buddhist|caste|dalit|obc|nationality|ethnic\w*|disabilit\w*|"
    r"handicap\w*|health\s+(?:condition|issue)s?|"
    r"accent(?!-|\s+(?:insensitive|sensitive|folding|marks?|normali)))\b",
    re.IGNORECASE,
)
_PROMPT = (files("hirevion_core.screening") / "prompts" / f"{PROMPT_VERSION}.md").read_text(
    encoding="utf-8"
)


class Quote(Trimmed):
    quote: str = Field(max_length=500)


class FactorAssessment(Trimmed):
    score: int = Field(ge=0, le=100)
    evidence: list[Quote] = Field(default_factory=list, max_length=5)


class AssessmentReply(Trimmed):
    roles: FactorAssessment
    projects: FactorAssessment
    domain: FactorAssessment
    education: FactorAssessment
    location: FactorAssessment
    strengths: list[str] = Field(default_factory=list, max_length=5)
    concerns: list[str] = Field(default_factory=list, max_length=5)
    missing_requirements: list[str] = Field(default_factory=list, max_length=10)


@dataclass(frozen=True, slots=True)
class Assessment:
    factors: dict[str, dict[str, Any]]
    """Per factor: `score`, `evidence` (verified quotes), `supported`."""
    strengths: list[str]
    concerns: list[str]
    missing: list[str]
    model: str


def _short(items: list[str]) -> list[str]:
    return [
        " ".join(item.split())[:200]
        for item in items
        if item.strip() and not _PROTECTED.search(item)
    ]


async def assess(
    llm: LLMService,
    organization_id: UUID,
    job_text: str,
    resume_text: str,
    *,
    application_id: UUID,
    evidence_optional: Collection[str] = EVIDENCE_OPTIONAL,
) -> Assessment:
    resume = fence(resume_text[:MAX_RESUME])
    if not resume.strip():  # nothing to assess: no call, and no score the resume didn't earn
        empty = {"score": 0, "evidence": [], "supported": False}
        return Assessment({name: dict(empty) for name in AI_FACTORS}, [], [], [], "none")
    messages: list[ChatMessage] = [
        {"role": "system", "content": _PROMPT},
        {
            "role": "user",
            "content": (
                f"<job>\n{fence(job_text[:MAX_JOB])}\n</job>\n\n<resume>\n{resume}\n</resume>"
            ),
        },
    ]
    context = AiContext(
        organization_id=organization_id,
        purpose=PURPOSE,
        prompt_version=PROMPT_VERSION,
        input_refs={"application": str(application_id)},
    )
    result = await llm.complete(context, messages, AssessmentReply, tier="strong")
    reply = result.value
    folded = fold(resume)
    factors: dict[str, dict[str, Any]] = {}
    for name in AI_FACTORS:
        item: FactorAssessment = getattr(reply, name)
        quotes = [q.quote for q in item.evidence if verified(q.quote, resume, folded_text=folded)]
        supported = bool(quotes) or name in evidence_optional
        score = item.score if supported else min(item.score, UNSUPPORTED_CAP)
        factors[name] = {"score": score, "evidence": quotes, "supported": supported}
    return Assessment(
        factors,
        _short(reply.strengths),
        _short(reply.concerns),
        _short(reply.missing_requirements),
        result.model,
    )
