"""The coding console's integrity signals (PRD §48; SP-16, ADR-0033).

The desktop reports typing starting and stopping, paste, copy, cut, focus and blur, with the
length of what went through the clipboard and never its text. This module adds them up for a
reviewer: how much of the final code arrived by paste, how long the candidate was away from the
code box, how long they typed. These are signals for a person to weigh, never proof: pasting from
one's own notes, or switching to read the question again, is ordinary. The statements describe
what happened and never conclude anything about the candidate.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

NOTABLE_PASTE_SHARE = 0.5
NOTABLE_AWAY_SECONDS = 60


@dataclass(frozen=True, slots=True)
class Event:
    kind: str
    occurred_at: datetime
    chars: int | None = None


@dataclass(frozen=True, slots=True)
class IntegritySignals:
    events: int
    pastes: int
    pasted_chars: int
    largest_paste: int
    paste_share: float | None
    copies: int
    cuts: int
    blurs: int
    time_away_seconds: int
    typing_seconds: int
    notable: bool
    statements: list[str]

    def as_json(self) -> dict[str, Any]:
        return {
            "events": self.events,
            "pastes": self.pastes,
            "pasted_chars": self.pasted_chars,
            "largest_paste": self.largest_paste,
            "paste_share": self.paste_share,
            "copies": self.copies,
            "cuts": self.cuts,
            "blurs": self.blurs,
            "time_away_seconds": self.time_away_seconds,
            "typing_seconds": self.typing_seconds,
            "notable": self.notable,
            "statements": self.statements,
        }


def _times(count: int) -> str:
    return "once" if count == 1 else f"{count} times"


def _spans(events: Sequence[Event], opens: str, closes: set[str], end: datetime) -> float:
    """Seconds between each `opens` event and the next of `closes` (or `end`)."""
    total, since = 0.0, None
    for event in events:
        if event.kind == opens and since is None:
            since = event.occurred_at
        elif event.kind in closes and since is not None:
            total += max(0.0, (event.occurred_at - since).total_seconds())
            since = None
    if since is not None:
        total += max(0.0, (end - since).total_seconds())
    return total


def integrity_signals(
    events: Sequence[Event], *, final_chars: int, closed_at: datetime
) -> IntegritySignals:
    """`final_chars`: the final code's length; `closed_at`: when the question ended (or now)."""
    ordered = sorted(events, key=lambda e: e.occurred_at)
    pastes = [e.chars or 0 for e in ordered if e.kind == "paste"]
    pasted = sum(pastes)
    share = round(min(1.0, pasted / final_chars), 2) if final_chars > 0 else None
    blurs = sum(e.kind == "blur" for e in ordered)
    away = round(_spans(ordered, "blur", {"focus"}, closed_at))
    typing = round(_spans(ordered, "typing_started", {"typing_stopped", "blur"}, closed_at))
    typed_at_all = any(e.kind == "typing_started" for e in ordered)
    statements: list[str] = []
    if not ordered:
        statements.append("No console activity was recorded.")
    if pastes:
        statements.append(
            f"Pasted {_times(len(pastes))}, {pasted} characters in all (the largest {max(pastes)})."
            if len(pastes) > 1
            else f"Pasted once, {pasted} characters."
        )
        if share is not None and share >= NOTABLE_PASTE_SHARE:
            statements.append(
                f"Pasted text adds up to {round(share * 100)}% of the final code's length."
            )
        if not typed_at_all:
            statements.append("No typing was recorded; the code arrived by paste.")
    if blurs:
        statements.append(f"Left the code box {_times(blurs)}, about {away} seconds in all.")
    if typed_at_all and not pastes:
        statements.append(f"Typed for about {typing} seconds; nothing was pasted.")
    notable = (share is not None and share >= NOTABLE_PASTE_SHARE) or away >= NOTABLE_AWAY_SECONDS
    return IntegritySignals(
        events=len(ordered),
        pastes=len(pastes),
        pasted_chars=pasted,
        largest_paste=max(pastes, default=0),
        paste_share=share if share is not None else (0.0 if not pastes else None),
        copies=sum(e.kind == "copy" for e in ordered),
        cuts=sum(e.kind == "cut" for e in ordered),
        blurs=blurs,
        time_away_seconds=away,
        typing_seconds=typing,
        notable=notable,
        statements=statements,
    )
