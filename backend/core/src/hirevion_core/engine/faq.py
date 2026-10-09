"""Final questions (PRD §35): the candidate's questions are answered only from the organisation's
FAQ. The match is deterministic word overlap, so the AI never invents company facts; a question
the FAQ doesn't cover is passed on to the recruiting team."""

from __future__ import annotations

import re
from collections.abc import Sequence

from hirevion_core.engine.context import FaqEntry

_STOPWORD_TEXT = """
a an and are as at be been being but by can could do does did for from get got had has
have how i if in into is it its just let like may me might more most my no not of on or
our out over please should so some such tell than that the their them then there these
they this those to too us very was we were what when where which while who whom why will
with would you your yours about any also am anything know want wondering question
questions ask
"""
STOPWORDS = frozenset(_STOPWORD_TEXT.split())
MIN_SCORE = 0.5


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def terms(text: str) -> set[str]:
    return {
        _stem(word)
        for word in re.findall(r"[a-z0-9]+", text.lower())
        if word not in STOPWORDS and len(word) > 1
    }


def match(question: str, faq: Sequence[FaqEntry]) -> FaqEntry | None:
    """The FAQ entry the candidate's question asks about, or None. An entry matches when at least
    half its question's terms appear, and at least two do (one, for a one-term entry)."""
    asked = terms(question)
    if not asked:
        return None
    best: tuple[float, int, FaqEntry] | None = None
    for index, entry in enumerate(faq):
        wanted = terms(entry.question)
        if not wanted:
            continue
        shared = len(asked & wanted)
        score = shared / len(wanted)
        if shared < min(2, len(wanted)) or score < MIN_SCORE:
            continue
        candidate = (score, -index, entry)
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    return best[2] if best else None
