"""The AI part of screening (PRD §15 "LLM reasoning where useful"): one structured call scoring
the factors rules can't (relevant roles, projects, domain, education, location), each with
quotes from the resume. Quotes are checked against the resume; a factor whose evidence doesn't
check out is capped, because a score must have evidence (PRD §16)."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from hirevion_core.ai.types import AiContext, ChatMessage, LLMService
from hirevion_core.documents.quotes import fold, verified

PROMPT_VERSION = "screening-assess-v1"
PURPOSE = "screening.assess"
UNSUPPORTED_CAP = 50
MAX_RESUME = 30_000
MAX_JOB = 12_000
# Factors that may be scored without quotes, when the job asks nothing of them.
EVIDENCE_OPTIONAL = frozenset({"education", "location"})
AI_FACTORS = ("roles", "projects", "domain", "education", "location")
_PROMPT = (files("hirevion_core.screening") / "prompts" / f"{PROMPT_VERSION}.md").read_text(
    encoding="utf-8"
)


class Quote(BaseModel):
    quote: str = Field(max_length=500)


class FactorAssessment(BaseModel):
    score: int = Field(ge=0, le=100)
    evidence: list[Quote] = Field(default_factory=list, max_length=5)


class AssessmentReply(BaseModel):
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
    return [" ".join(item.split())[:200] for item in items if item.strip()]


async def assess(
    llm: LLMService,
    organization_id: UUID,
    job_text: str,
    resume_text: str,
    *,
    application_id: UUID,
) -> Assessment:
    resume = resume_text[:MAX_RESUME]
    messages: list[ChatMessage] = [
        {"role": "system", "content": _PROMPT},
        {
            "role": "user",
            "content": f"<job>\n{job_text[:MAX_JOB]}\n</job>\n\n<resume>\n{resume}\n</resume>",
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
        supported = bool(quotes) or name in EVIDENCE_OPTIONAL
        score = item.score if supported else min(item.score, UNSUPPORTED_CAP)
        factors[name] = {"score": score, "evidence": quotes, "supported": supported}
    return Assessment(
        factors,
        _short(reply.strengths),
        _short(reply.concerns),
        _short(reply.missing_requirements),
        result.model,
    )
