"""Normalising extracted text, and finding the sections of a job description or resume by their
headings."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Invisible characters that hide or reorder text: zero-width ones, bidi overrides and isolates,
# the word joiner and the byte-order mark. Resumes use them to smuggle keywords (SP-04b flags).
_HIDDEN = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿]")

# Headings, by the section they open. Matched on a line of their own, any case, with an
# optional colon.
_HEADINGS: dict[str, tuple[str, ...]] = {
    "about": ("about us", "about the company", "about the role", "who we are", "overview"),
    "summary": ("summary", "profile", "professional summary", "objective"),
    "responsibilities": (
        "responsibilities",
        "key responsibilities",
        "what you will do",
        "what you'll do",
        "your role",
        "duties",
        "the role",
    ),
    "requirements": (
        "requirements",
        "must have",
        "must-have",
        "what you need",
        "what we're looking for",
        "what we are looking for",
        "minimum qualifications",
    ),
    "preferred": (
        "nice to have",
        "nice-to-have",
        "preferred qualifications",
        "good to have",
        "bonus points",
        "preferred",
    ),
    "qualifications": ("qualifications", "education", "educational qualifications"),
    "skills": ("skills", "technical skills", "tech stack", "technologies", "key skills"),
    "experience": (
        "experience",
        "work experience",
        "employment history",
        "professional experience",
    ),
    "projects": ("projects",),
    "certifications": ("certifications", "certificates", "licenses"),
    "benefits": ("benefits", "perks", "what we offer", "why join us", "compensation"),
    "location": ("location", "work location", "work model"),
}
_HEADING_LINE = re.compile(r"^[ \t#*•\-]*([A-Za-z][A-Za-z '\u2019\-]{1,40}?)[ \t]*:?[ \t]*$", re.M)
_LOOKUP = {heading: name for name, headings in _HEADINGS.items() for heading in headings}


@dataclass(frozen=True, slots=True)
class Section:
    name: str
    start: int
    end: int


def normalise(text: str) -> tuple[str, int]:
    """NFKC text with unified line breaks, single spaces and at most one blank line in a row,
    and how many hidden characters were removed."""
    hidden = len(_HIDDEN.findall(text))
    text = _HIDDEN.sub("", text)
    text = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in text.replace("\f", "\n\f\n").split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text, hidden


def detect(text: str) -> list[Section]:
    """The sections whose headings the text uses, in order; each runs to the next heading."""
    found: list[tuple[str, int, int]] = []
    for match in _HEADING_LINE.finditer(text):
        name = _LOOKUP.get(match.group(1).strip().lower().replace("\u2019", "'"))
        if name is not None:
            found.append((name, match.start(), match.end()))
    return [
        Section(name, body_start, found[index + 1][1] if index + 1 < len(found) else len(text))
        for index, (name, _, body_start) in enumerate(found)
    ]
