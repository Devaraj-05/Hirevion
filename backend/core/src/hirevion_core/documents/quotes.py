"""Evidence checks: a quote the AI gives must really be in the document (master plan §3.2(3)).
Comparison ignores case, line breaks and runs of spaces, and the style of quotes and dashes."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

from hirevion_core.jobs.synonyms import related_terms

_FOLD = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
    }
)
_SPACE = re.compile(r"\s+")
_TOKEN = re.compile(r"[a-z0-9][a-z0-9+#.]*")
# A quote needs this many letters or digits to count as evidence: one character is in every text.
MIN_QUOTE_CHARACTERS = 2


def fold(text: str) -> str:
    """The form quotes are compared in."""
    text = unicodedata.normalize("NFKC", text).translate(_FOLD).lower()
    return _SPACE.sub(" ", text).strip()


def _tokens(text: str) -> set[str]:
    return {token.rstrip(".") for token in _TOKEN.findall(fold(text))}


def tied(quote: str, values: Sequence[str]) -> bool:
    """Whether a quote is about the values it supports: it shares a word with at least one of
    them (words of four letters or more may be part of one another, as "Postgres" is of
    "PostgreSQL"). With no value to compare, there is nothing to tie it to."""
    wanted = [value for value in values if value and value.strip()]
    if not wanted:
        return True
    words = _tokens(quote)
    for value in wanted:
        spellings = [value, *related_terms(value)]
        for token in set().union(*(_tokens(spelling) for spelling in spellings)):
            if token in words or any(
                min(len(token), len(word)) >= 4 and (token in word or word in token)
                for word in words
            ):
                return True
    return False


def verified(
    quote: str,
    text: str,
    *,
    folded_text: str | None = None,
    values: Sequence[str] = (),
) -> bool:
    """Whether `quote` appears in `text` (pass `folded_text` to check many quotes cheaply), is
    long enough to be evidence, and is about the `values` it supports."""
    needle = fold(quote)
    if sum(char.isalnum() for char in needle) < MIN_QUOTE_CHARACTERS:
        return False
    if needle not in (folded_text if folded_text is not None else fold(text)):
        return False
    return tied(quote, values)
