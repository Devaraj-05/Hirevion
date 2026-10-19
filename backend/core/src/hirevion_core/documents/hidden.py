"""Flags for resumes that try to steer an AI screener (master plan §3.2(3)): text a reader
can't see, invisible characters, long metadata, and instruction-like phrases. The resume is still
read, as data; the flags reach the candidate, and the recruiter sees them."""

from __future__ import annotations

import re
from typing import Any

from hirevion_core.documents.text import ExtractedText

SAMPLE = 200
METADATA_LIMIT = 200

_PHRASES = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:ignore|disregard|forget)\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|"
        r"earlier|preceding)?\s*(?:instructions|prompts?|rules|directions)\b",
        r"\bdisregard\s+(?:everything|all)\s+(?:above|before)\b",
        r"\byou\s+are\s+(?:now\s+)?(?:an?|the)\s+(?:[a-z]+\s+){0,2}(?:ai|assistant|model|"
        r"language\s+model|chatbot)\b",
        r"\b(?:system|developer)\s+prompt\b",
        r"\brank\s+(?:me|this\s+(?:candidate|resume|applicant))\s+(?:as\s+)?(?:first|highest|top|"
        r"#?1)\b",
        r"\bscore\s+(?:me|this\s+(?:candidate|resume))\s+(?:a\s+)?(?:10|100|ten|full\s+marks)\b",
        r"\b(?:this|the)\s+candidate\s+is\s+(?:a\s+)?perfect\s+(?:match|fit)\b",
        r"\bdo\s+not\s+(?:reject|screen\s+out)\b",
    )
]


# The phrases that have no place in a resume at all. The others ("system prompt", "you are an AI
# assistant") are flagged but kept: an engineer's resume can say them for honest reasons.
_STRONG = _PHRASES[:2] + _PHRASES[4:]
REDACTED = "[instruction-like text removed]"


def redact(text: str) -> tuple[str, int]:
    """`text` without its most plain instructions to a screener ("ignore all previous
    instructions", "rank this candidate first"), and how many were removed. They stay in the
    flags, so a recruiter sees what was there; the AI never reads them."""
    spans = sorted((m.start(), m.end()) for pattern in _STRONG for m in pattern.finditer(text))
    pieces: list[str] = []
    position = count = 0
    for start, end in spans:
        if start < position:
            continue
        pieces += [text[position:start], REDACTED]
        position = end
        count += 1
    pieces.append(text[position:])
    return "".join(pieces), count


def injection_phrases(text: str) -> list[str]:
    """The instruction-like phrases in `text`, lower-cased, in order, without repeats."""
    found: list[tuple[int, str]] = []
    for pattern in _PHRASES:
        found += [(m.start(), " ".join(m.group().lower().split())) for m in pattern.finditer(text)]
    seen: list[str] = []
    for _, phrase in sorted(found):
        if phrase not in seen:
            seen.append(phrase)
    return seen


def inspect(extracted: ExtractedText, *, zero_width: int) -> dict[str, Any]:
    """The document's safety flags; empty when there's nothing to report."""
    flags: dict[str, Any] = {}
    hidden = " ".join(extracted.hidden.split())
    if hidden:
        flags["hidden_text"] = {"characters": len(hidden), "sample": hidden[:SAMPLE]}
    if zero_width:
        flags["zero_width"] = zero_width
    long_metadata = " ".join(
        value for value in extracted.metadata.values() if len(value) > METADATA_LIMIT
    )
    if long_metadata:
        flags["metadata_text"] = {
            "characters": len(long_metadata),
            "sample": long_metadata[:SAMPLE],
        }
    phrases = injection_phrases(
        "\n".join([extracted.text, extracted.hidden, *extracted.metadata.values()])
    )
    if phrases:
        flags["injection"] = phrases
    return flags
