"""Evidence checks: a quote the AI gives must really be in the document (master plan §3.2(3)).
Comparison ignores case, line breaks and runs of spaces, and the style of quotes and dashes."""

from __future__ import annotations

import re
import unicodedata

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


def fold(text: str) -> str:
    """The form quotes are compared in."""
    text = unicodedata.normalize("NFKC", text).translate(_FOLD).lower()
    return _SPACE.sub(" ", text).strip()


def verified(quote: str, text: str, *, folded_text: str | None = None) -> bool:
    """Whether `quote` appears in `text` (pass `folded_text` to check many quotes cheaply)."""
    needle = fold(quote)
    return bool(needle) and needle in (folded_text if folded_text is not None else fold(text))
