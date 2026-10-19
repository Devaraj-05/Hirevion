"""The job-description extraction (PRD §12): one structured AI call, then every item checked
against the text. Items whose quote isn't in the description are dropped and counted."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from typing import Literal
from uuid import UUID

from pydantic import Field

from hirevion_core.ai.types import AiContext, ChatMessage, LLMService
from hirevion_core.documents.prompt_text import fence
from hirevion_core.documents.quotes import fold, verified
from hirevion_core.documents.trimmed import Trimmed

PROMPT_VERSION = "jd-extract-v1"
PURPOSE = "jd.extract"
# Long enough for any real job description; more is pasted noise and cost.
MAX_CHARACTERS = 30_000
_PROMPT = (files("hirevion_core.documents") / "prompts" / f"{PROMPT_VERSION}.md").read_text(
    encoding="utf-8"
)


class QuotedSkill(Trimmed):
    name: str = Field(max_length=100)
    quote: str = Field(max_length=500)


class Quoted(Trimmed):
    text: str = Field(max_length=500)
    quote: str = Field(max_length=500)


class JdExtraction(Trimmed):
    title: str | None = Field(default=None, max_length=200)
    required_skills: list[QuotedSkill] = Field(default_factory=list, max_length=60)
    preferred_skills: list[QuotedSkill] = Field(default_factory=list, max_length=60)
    experience_min: float | None = Field(default=None, ge=0, le=60)
    experience_max: float | None = Field(default=None, ge=0, le=60)
    responsibilities: list[Quoted] = Field(default_factory=list, max_length=50)
    qualifications: list[Quoted] = Field(default_factory=list, max_length=50)
    domain: list[Quoted] = Field(default_factory=list, max_length=20)
    location: str | None = Field(default=None, max_length=200)
    work_model: Literal["onsite", "hybrid", "remote"] | None = None


@dataclass(frozen=True, slots=True)
class JdResult:
    extraction: JdExtraction
    """Only the items whose quotes were found in the text."""
    dropped: int
    model: str
    truncated: bool = False
    """The description was longer than the AI is given, so its end wasn't read."""


async def extract_jd(
    llm: LLMService, organization_id: UUID, text: str, *, document_id: UUID
) -> JdResult:
    sample = fence(text[:MAX_CHARACTERS])
    messages: list[ChatMessage] = [
        {"role": "system", "content": _PROMPT},
        {"role": "user", "content": f"<job_description>\n{sample}\n</job_description>"},
    ]
    context = AiContext(
        organization_id=organization_id,
        purpose=PURPOSE,
        prompt_version=PROMPT_VERSION,
        input_refs={"document": str(document_id)},
    )
    result = await llm.complete(context, messages, JdExtraction, tier="strong")
    folded = fold(sample)
    raw = result.value
    dropped = 0

    def keep[T: (QuotedSkill, Quoted)](items: list[T]) -> list[T]:
        nonlocal dropped
        found = [
            item
            for item in items
            if verified(
                item.quote,
                sample,
                folded_text=folded,
                values=[item.name if isinstance(item, QuotedSkill) else item.text],
            )
        ]
        dropped += len(items) - len(found)
        return found

    checked = raw.model_copy(
        update={
            "required_skills": keep(raw.required_skills),
            "preferred_skills": keep(raw.preferred_skills),
            "responsibilities": keep(raw.responsibilities),
            "qualifications": keep(raw.qualifications),
            "domain": keep(raw.domain),
        }
    )
    return JdResult(checked, dropped, result.model, truncated=len(text) > MAX_CHARACTERS)
