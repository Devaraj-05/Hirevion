"""Turns the third eye's detections into episodes (C7-1; product owner, 2026-11-16; PRD §53).

A frame shows a second person when two or more people of a reasonable size are in it, and a
phone when any phone is. An episode starts once that holds for a while (3 s for a person, 2 s
for a phone), tolerating a missed frame, and ends 5 s after the last sighting. The same kind
opens at most one episode a minute, so one situation isn't flagged over and over. Episodes are
evidence for the recruiter, never proof.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

Kind = Literal["unexpected_person", "phone"]
KINDS: tuple[Kind, ...] = ("phone", "unexpected_person")
EVENTS: dict[Kind, str] = {
    "unexpected_person": "UNEXPECTED_PERSON_DETECTED",
    "phone": "PHONE_DETECTED",
}

PERSON_MIN_SCORE = 0.5
# Smaller than this share of the picture is a poster, a photo or a far reflection, not a person.
PERSON_MIN_AREA = 0.02
PHONE_MIN_SCORE = 0.4
HOLD_SECONDS: dict[Kind, float] = {"unexpected_person": 3.0, "phone": 2.0}
# A missed frame (the detector flickers) doesn't break a run; a longer gap does.
GAP_SECONDS = 1.0
CLEAR_AFTER_SECONDS = 5.0
COOLDOWN_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class Detection:
    label: str
    score: float
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True, slots=True)
class Started:
    kind: Kind
    at: float
    """When the thing was first seen in this run (seconds)."""


@dataclass(frozen=True, slots=True)
class Ended:
    kind: Kind
    at: float
    """When it was last seen."""
    started_at: float


def seen(detections: Iterable[Detection], width: int, height: int) -> dict[Kind, bool]:
    """What one frame shows: a second person, a phone."""
    least = PERSON_MIN_AREA * width * height
    people = 0
    phone = False
    for found in detections:
        if found.label == "person" and found.score >= PERSON_MIN_SCORE:
            if found.width * found.height >= least:
                people += 1
        elif found.label == "cell phone" and found.score >= PHONE_MIN_SCORE:
            phone = True
    return {"unexpected_person": people >= 2, "phone": phone}


@dataclass(slots=True)
class _Track:
    since: float | None = None
    last_seen: float | None = None
    open_since: float | None = None
    last_started: float | None = None


class Watch:
    """Feeds frames in time order; returns what started or ended at each."""

    def __init__(self) -> None:
        self._tracks: dict[Kind, _Track] = {kind: _Track() for kind in KINDS}

    def update(self, now: float, flags: Mapping[Kind, bool]) -> list[Started | Ended]:
        happened: list[Started | Ended] = []
        for kind in KINDS:
            track = self._tracks[kind]
            if flags.get(kind, False):
                if track.since is None:
                    track.since = now
                track.last_seen = now
                cooled = track.last_started is None or now - track.last_started >= COOLDOWN_SECONDS
                if track.open_since is None and now - track.since >= HOLD_SECONDS[kind] and cooled:
                    track.open_since = track.since
                    track.last_started = now
                    happened.append(Started(kind, track.since))
                continue
            last = track.last_seen
            if track.open_since is not None:
                if last is not None and now - last >= CLEAR_AFTER_SECONDS:
                    happened.append(Ended(kind, last, track.open_since))
                    track.open_since = None
                    track.since = None
            elif last is None or now - last >= GAP_SECONDS:
                track.since = None
        return happened
