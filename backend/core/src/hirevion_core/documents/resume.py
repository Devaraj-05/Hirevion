"""The resume parse (PRD §14): one structured AI call over the masked text, then every item
checked against the text, with its page and section kept as evidence. Items whose quote isn't
in the resume are dropped and counted; an email or phone must also be one the text contains."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.resources import files
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from hirevion_core.ai.types import AiContext, ChatMessage, LLMService
from hirevion_core.documents import pii
from hirevion_core.documents.quotes import fold, verified
from hirevion_core.documents.sections import Section, detect

PROMPT_VERSION = "resume-parse-v1"
PURPOSE = "resume.parse"
MAX_CHARACTERS = 40_000
_PROMPT = (files("hirevion_core.documents") / "prompts" / f"{PROMPT_VERSION}.md").read_text(
    encoding="utf-8"
)
_TEXT = 500
_YEARS = Field(None, ge=0, le=60)


class Quoted(BaseModel):
    quote: str = Field(max_length=_TEXT)


class QuotedValue(Quoted):
    value: str = Field(max_length=2000)


class SkillItem(Quoted):
    name: str = Field(max_length=100)
    years: float | None = _YEARS


class Position(Quoted):
    company: str | None = Field(None, max_length=200)
    title: str | None = Field(None, max_length=200)
    start: str | None = Field(None, max_length=20)
    end: str | None = Field(None, max_length=20)
    current: bool = False


class Education(Quoted):
    institution: str | None = Field(None, max_length=200)
    degree: str | None = Field(None, max_length=200)
    field: str | None = Field(None, max_length=200)
    start: str | None = Field(None, max_length=20)
    end: str | None = Field(None, max_length=20)


class Certification(Quoted):
    name: str = Field(max_length=200)
    issuer: str | None = Field(None, max_length=200)
    year: str | None = Field(None, max_length=20)


class Project(Quoted):
    name: str = Field(max_length=200)
    description: str | None = Field(None, max_length=_TEXT)


class TextItem(Quoted):
    text: str = Field(max_length=_TEXT)


class Language(Quoted):
    name: str = Field(max_length=100)


class Link(Quoted):
    url: str = Field(max_length=500)


class ResumeExtraction(BaseModel):
    name: QuotedValue | None = None
    email: QuotedValue | None = None
    phone: QuotedValue | None = None
    location: QuotedValue | None = None
    summary: QuotedValue | None = None
    skills: list[SkillItem] = Field(default_factory=list, max_length=150)
    total_experience_years: float | None = _YEARS
    positions: list[Position] = Field(default_factory=list, max_length=40)
    education: list[Education] = Field(default_factory=list, max_length=20)
    certifications: list[Certification] = Field(default_factory=list, max_length=40)
    projects: list[Project] = Field(default_factory=list, max_length=40)
    achievements: list[TextItem] = Field(default_factory=list, max_length=40)
    languages: list[Language] = Field(default_factory=list, max_length=20)
    links: list[Link] = Field(default_factory=list, max_length=20)


SINGLE_FIELDS = ("name", "email", "phone", "location", "summary")
LIST_FIELDS = (
    "skills",
    "positions",
    "education",
    "certifications",
    "projects",
    "achievements",
    "languages",
    "links",
)


@dataclass(frozen=True, slots=True)
class ResumeResult:
    profile: dict[str, Any]
    """The verified extraction; every item carries its `quote`, `page` and `section`."""
    dropped: int
    model: str


class _Evidence:
    """Finds where in the resume a quote comes from."""

    def __init__(self, text: str, page_texts: Sequence[str]) -> None:
        self.text = text
        self.folded = fold(text)
        self.pages = [fold(page) for page in page_texts]
        self.sections: list[Section] = detect(text)

    def found(self, quote: str) -> bool:
        return verified(quote, self.text, folded_text=self.folded)

    def locate(self, quote: str) -> dict[str, Any]:
        needle = fold(quote)
        page = next(
            (number for number, page in enumerate(self.pages, start=1) if needle in page), None
        )
        pattern = r"\s+".join(re.escape(word) for word in quote.split())
        match = re.search(pattern, self.text, re.IGNORECASE) if pattern else None
        section = (
            next(
                (s.name for s in self.sections if s.start <= match.start() < s.end),
                None,
            )
            if match
            else None
        )
        return {"page": page, "section": section}


def _contact_ok(field: str, value: str, found: list[pii.PiiMatch]) -> bool:
    if field == "email":
        return any(m.kind == "email" and m.value.lower() == value.lower() for m in found)
    if field == "phone":
        wanted = pii.normalise_phone(value)
        return wanted is not None and any(
            m.kind == "phone" and pii.normalise_phone(m.value) == wanted for m in found
        )
    return True


async def parse_resume(
    llm: LLMService,
    organization_id: UUID,
    text: str,
    page_texts: Sequence[str],
    *,
    document_id: UUID,
) -> ResumeResult:
    """`text` is the resume's visible, normalised text (masked here, again, to be sure)."""
    sample = pii.mask(text).text[:MAX_CHARACTERS]
    pages = [pii.mask(page).text for page in page_texts]
    messages: list[ChatMessage] = [
        {"role": "system", "content": _PROMPT},
        {"role": "user", "content": f"<resume>\n{sample}\n</resume>"},
    ]
    context = AiContext(
        organization_id=organization_id,
        purpose=PURPOSE,
        prompt_version=PROMPT_VERSION,
        input_refs={"document": str(document_id)},
    )
    result = await llm.complete(context, messages, ResumeExtraction, tier="strong")
    raw = result.value
    evidence = _Evidence(sample, pages)
    contacts = pii.find(sample)
    dropped = 0
    profile: dict[str, Any] = {"total_experience_years": raw.total_experience_years}

    for name in SINGLE_FIELDS:
        item: QuotedValue | None = getattr(raw, name)
        if item is None:
            profile[name] = None
        elif evidence.found(item.quote) and _contact_ok(name, item.value, contacts):
            profile[name] = {**item.model_dump(), **evidence.locate(item.quote)}
        else:
            profile[name] = None
            dropped += 1
    for name in LIST_FIELDS:
        kept = []
        for entry in getattr(raw, name):
            if evidence.found(entry.quote):
                kept.append({**entry.model_dump(), **evidence.locate(entry.quote)})
            else:
                dropped += 1
        profile[name] = kept
    return ResumeResult(profile, dropped, result.model)
