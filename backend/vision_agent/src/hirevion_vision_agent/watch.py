"""Turns the third eye's detections into episodes (C7-1; product owner, 2026-11-16; PRD §53).

A frame shows a second person when two or more people of a reasonable size are in it, and a
phone when any phone is. An episode starts once that holds for a while (3 s for a person, 2 s
for a phone), tolerating a missed frame, and ends 5 s after the last sighting. The same kind
opens at most one episode a minute, so one situation isn't flagged over and over. Episodes are
evidence for the recruiter, never proof.

C7-2 (2026-11-26) adds PRD §53's other signals, each with its own hold: a secondary screen (a
second screen besides the candidate's own: any two monitors, TVs or laptops) held 5 s; the
candidate out of view (nobody in a readable picture, counted only once they had been seen) held
10 s; hands out of view (the pose's wrists) held 15 s; unusual movement held 4 s; and the view
changed (the phone moved, turned away or covered) held 5 s. Each hold is at least its warning
tier, so an episode is a warning when it is first recorded and alerts live. The last three come
from `scene.py` and `pose.py`; the episode logic is the same for all.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

Kind = Literal[
    "unexpected_person",
    "phone",
    "secondary_screen",
    "left_view",
    "hands_out_of_view",
    "unusual_movement",
    "view_changed",
]
KINDS: tuple[Kind, ...] = (
    "phone",
    "unexpected_person",
    "secondary_screen",
    "left_view",
    "hands_out_of_view",
    "unusual_movement",
    "view_changed",
)
EVENTS: dict[Kind, str] = {
    "unexpected_person": "UNEXPECTED_PERSON_DETECTED",
    "phone": "PHONE_DETECTED",
    "secondary_screen": "SECONDARY_SCREEN_DETECTED",
    "left_view": "CANDIDATE_LEFT_VIEW",
    "hands_out_of_view": "HANDS_OUT_OF_VIEW",
    "unusual_movement": "UNUSUAL_MOVEMENT",
    "view_changed": "THIRD_EYE_VIEW_CHANGED",
}

PERSON_MIN_SCORE = 0.5
# Smaller than this share of the picture is a poster, a photo or a far reflection, not a person.
PERSON_MIN_AREA = 0.02
PHONE_MIN_SCORE = 0.4
SCREEN_MIN_SCORE = 0.5
# A screen smaller than this share of the picture is too far away to read.
SCREEN_MIN_AREA = 0.01
# Two laptop boxes overlapping this much are one laptop found twice.
SAME_BOX_IOU = 0.3
SCREENS = ("tv", "laptop")
HOLD_SECONDS: dict[Kind, float] = {
    "unexpected_person": 3.0,
    "phone": 2.0,
    "secondary_screen": 5.0,
    "left_view": 10.0,
    "hands_out_of_view": 15.0,
    "unusual_movement": 4.0,
    "view_changed": 5.0,
}
# A missed frame (the detector flickers) doesn't break a run; a longer gap does. A longer hold
# allows a proportionally longer gap (C7-2's evaluation: hands, held 15 s, lost a fifth of their
# episodes to two missed looks in a row), with the share below as the guard.
GAP_SECONDS = 1.0
LONG_GAP_SHARE = 0.15


def gap_seconds(kind: Kind) -> float:
    return max(GAP_SECONDS, LONG_GAP_SHARE * HOLD_SECONDS[kind])


# And the run must show the thing in most looks: two short false sightings a frame apart aren't a
# held one (C7-2's evaluation: they were most of the phone's false positives).
HOLD_SHARE = 0.7
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


def people_and_phones(
    detections: Iterable[Detection], width: int, height: int
) -> tuple[list[Detection], list[Detection]]:
    """The people (sure enough, and big enough to be in the room) and the phones a frame shows."""
    least = PERSON_MIN_AREA * width * height
    people: list[Detection] = []
    phones: list[Detection] = []
    for found in detections:
        if found.label == "person" and found.score >= PERSON_MIN_SCORE:
            if found.width * found.height >= least:
                people.append(found)
        elif found.label == "cell phone" and found.score >= PHONE_MIN_SCORE:
            phones.append(found)
    return people, phones


def _iou(a: Detection, b: Detection) -> float:
    left, top = max(a.x, b.x), max(a.y, b.y)
    right, bottom = min(a.x + a.width, b.x + b.width), min(a.y + a.height, b.y + b.height)
    inter = max(0.0, right - left) * max(0.0, bottom - top)
    union = a.width * a.height + b.width * b.height - inter
    return inter / union if union > 0 else 0.0


def screens(detections: Iterable[Detection], width: int, height: int) -> list[Detection]:
    """The monitors, TVs and laptops big and sure enough to count, a laptop found twice once."""
    least = SCREEN_MIN_AREA * width * height
    kept: list[Detection] = []
    for found in sorted(detections, key=lambda d: -d.score):
        if found.label not in SCREENS or found.score < SCREEN_MIN_SCORE:
            continue
        if found.width * found.height < least:
            continue
        if any(_iou(found, other) >= SAME_BOX_IOU for other in kept):
            continue
        kept.append(found)
    return kept


def seen(detections: Iterable[Detection], width: int, height: int) -> dict[Kind, bool]:
    """What one frame shows: a second person, a phone, a secondary screen, nobody at all. One
    screen in view is the candidate's own (a laptop, or the monitor of a desktop PC, which COCO
    calls `tv`); a second one is the signal (review, 2026-11-26)."""
    found = list(detections)
    people, phones = people_and_phones(found, width, height)
    return {
        "unexpected_person": len(people) >= 2,
        "phone": bool(phones),
        "secondary_screen": len(screens(found, width, height)) >= 2,
        "left_view": not people,
    }


@dataclass(slots=True)
class _Track:
    since: float | None = None
    last_seen: float | None = None
    looks: int = 0
    sightings: int = 0
    open_since: float | None = None
    last_started: float | None = None


class Watch:
    """Feeds frames in time order; returns what started or ended at each."""

    def __init__(self) -> None:
        self._tracks: dict[Kind, _Track] = {kind: _Track() for kind in KINDS}
        # Out of view means something only once the candidate has been in it.
        self._candidate_seen = False

    def last_seen(self, kind: Kind) -> float | None:
        """When the kind was last seen (its open episode's latest sighting)."""
        return self._tracks[kind].last_seen

    def update(self, now: float, flags: Mapping[Kind, bool]) -> list[Started | Ended]:
        """A kind missing from `flags` is unknown in this frame (a covered picture says nothing
        about where the candidate is): its track stays as it was (review, 2026-11-26)."""
        happened: list[Started | Ended] = []
        if flags.get("left_view") is False:
            self._candidate_seen = True
        for kind in KINDS:
            if kind not in flags:
                continue
            track = self._tracks[kind]
            active = flags.get(kind, False) and (kind != "left_view" or self._candidate_seen)
            if track.since is not None:
                track.looks += 1
            if active:
                if track.since is None:
                    track.since, track.looks, track.sightings = now, 1, 0
                track.sightings += 1
                track.last_seen = now
                cooled = track.last_started is None or now - track.last_started >= COOLDOWN_SECONDS
                if not cooled and track.open_since is None:
                    # Still the minute after the last episode: a new one, if any, starts after it.
                    track.since, track.looks, track.sightings = now, 1, 1
                held = (
                    now - track.since >= HOLD_SECONDS[kind]
                    and track.sightings >= HOLD_SHARE * track.looks
                )
                if track.open_since is None and held and cooled:
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
            elif last is None or now - last >= gap_seconds(kind):
                track.since = None
        return happened

    def close_all(self) -> list[Ended]:
        """The open episodes, ended where they were last seen (the watch is stopping)."""
        ended: list[Ended] = []
        for kind in KINDS:
            track = self._tracks[kind]
            if track.open_since is not None and track.last_seen is not None:
                ended.append(Ended(kind, track.last_seen, track.open_since))
            track.open_since = None
            track.since = None
        return ended
