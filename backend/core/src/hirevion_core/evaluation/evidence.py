"""Evidence: a quote the model gives must really be in the candidate's words (master plan §3.2(3),
the same rule as screening's resume quotes, ADR-0016).

A quote is checked against the stored transcript turns, ignoring case, line breaks, runs of
spaces and the style of quotes and dashes (`documents.quotes.fold`). It must sit inside one turn,
so it carries that turn's number and times (PRD §41), and it must be long enough to prove
something. What is not found is dropped; a score left with nothing is capped by the caller.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from hirevion_core.documents.quotes import fold

MIN_QUOTE = 6  # characters, after folding
MAX_QUOTES = 3
_TRIM = " \t\r\n\"'“”‘’.…"  # noqa: RUF001 (the curly quotes are the point)


@dataclass(frozen=True, slots=True)
class Turn:
    """One stored transcript segment, as evidence sees it."""

    seq: int
    text: str
    start_ms: int
    end_ms: int
    question_id: str | None = None


@dataclass(frozen=True, slots=True)
class Evidence:
    """A verified quote and where it was said."""

    quote: str
    seq: int
    start_ms: int
    end_ms: int
    question_id: str | None

    def as_json(self) -> dict[str, Any]:
        return {
            "quote": self.quote,
            "seq": self.seq,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "question_id": self.question_id,
        }


def clean(quote: str) -> str:
    """A quote without the quotation marks and ellipses models put around it."""
    return quote.strip(_TRIM)


class Quotable:
    """The turns quotes can be checked against (folded once, for many quotes)."""

    def __init__(self, turns: Sequence[Turn]) -> None:
        self._turns = [(turn, fold(turn.text)) for turn in turns]

    def locate(self, quote: str, *, question_id: str | None = None) -> Turn | None:
        needle = fold(clean(quote))
        if len(needle) < MIN_QUOTE:
            return None
        for turn, folded in self._turns:
            if question_id is not None and turn.question_id != question_id:
                continue
            if needle in folded:
                return turn
        return None

    def verify(
        self, quotes: Iterable[str], *, question_id: str | None = None, limit: int = MAX_QUOTES
    ) -> list[Evidence]:
        """The quotes that are really there (in `question_id`'s turns, when given), once each, in
        the order given, at most `limit`."""
        found: list[Evidence] = []
        seen: set[str] = set()
        for raw in quotes:
            text = clean(raw)
            key = fold(text)
            if key in seen:
                continue
            turn = self.locate(text, question_id=question_id)
            if turn is None:
                continue
            seen.add(key)
            found.append(Evidence(text, turn.seq, turn.start_ms, turn.end_ms, turn.question_id))
            if len(found) == limit:
                break
        return found
