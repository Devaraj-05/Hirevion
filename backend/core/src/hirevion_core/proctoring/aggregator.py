"""The temporal aggregator (PRD §54's third stage): which sequence numbers have arrived, and which
events are one episode.

A device may report one episode up to three times (`details.phase` `started`, `escalated`,
`ended`, with the same `event` and `started_at`). They are stored as one row that is updated in
place, never as three incidents, and a late older phase never undoes a newer one.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from hirevion_core.proctoring.catalogue import PHASE_RANK
from hirevion_core.proctoring.normaliser import Normalised

MISSING_LIMIT = 500
MAX_JUMP = 100_000
"""The furthest a sequence number may run ahead of the highest one received."""


@dataclass(frozen=True, slots=True)
class Offer:
    status: Literal["new", "fill", "duplicate"]
    opened_gap: tuple[int, int] | None = None


class SeqTracker:
    """The highest sequence number received and the ranges below it still missing, each with
    when it was first seen missing and whether the server reported it (a gap that fills in within
    the grace period is never reported)."""

    def __init__(self, max_seq: int = 0, gaps: list[list[Any]] | None = None) -> None:
        self.max_seq = max_seq
        self.gaps: list[tuple[int, int]] = []
        self._since: list[float] = []
        self._reported: list[bool] = []
        for gap in gaps or []:
            self.gaps.append((int(gap[0]), int(gap[1])))
            self._since.append(float(gap[2]) if len(gap) > 2 else 0.0)
            self._reported.append(bool(gap[3]) if len(gap) > 3 else False)

    @property
    def acked_through(self) -> int:
        """Everything up to here has arrived."""
        return self.gaps[0][0] - 1 if self.gaps else self.max_seq

    def too_far(self, seq: int) -> bool:
        return seq < 1 or seq > self.max_seq + MAX_JUMP

    def offer(self, seq: int, now: float = 0.0) -> Offer:
        """Takes sequence number `seq`, received at `now` (seconds since the epoch)."""
        if seq > self.max_seq:
            gap = (self.max_seq + 1, seq - 1) if seq > self.max_seq + 1 else None
            if gap is not None:
                self.gaps.append(gap)
                self._since.append(now)
                self._reported.append(False)
            self.max_seq = seq
            return Offer("new", gap)
        for index, (low, high) in enumerate(self.gaps):
            if low <= seq <= high:
                pieces = []
                if seq > low:
                    pieces.append((low, seq - 1))
                if seq < high:
                    pieces.append((seq + 1, high))
                since, reported = self._since[index], self._reported[index]
                self.gaps[index : index + 1] = pieces
                self._since[index : index + 1] = [since] * len(pieces)
                self._reported[index : index + 1] = [reported] * len(pieces)
                return Offer("fill")
        return Offer("duplicate")

    def overdue(self, now: float, grace: float) -> list[tuple[int, int]]:
        """The ranges still missing after `grace` seconds that haven't been reported yet."""
        return [
            gap
            for gap, since, reported in zip(self.gaps, self._since, self._reported, strict=True)
            if not reported and now - since > grace
        ]

    def mark_reported(self, ranges: list[tuple[int, int]]) -> None:
        for index, gap in enumerate(self.gaps):
            if gap in ranges:
                self._reported[index] = True

    def next_report(self, grace: float) -> float | None:
        """When the earliest unreported range becomes overdue."""
        times = [s + grace for s, r in zip(self._since, self._reported, strict=True) if not r]
        return min(times) if times else None

    def missing(self, high: int | None = None, limit: int = MISSING_LIMIT) -> list[int]:
        """The numbers still missing, lowest first; with `high` (a heartbeat's `seq_high`) also
        what the device has produced beyond the highest received."""
        ranges = list(self.gaps)
        if high is not None and high > self.max_seq:
            ranges.append((self.max_seq + 1, high))
        numbers: list[int] = []
        for low, upper in ranges:
            numbers.extend(range(low, min(upper, low + limit - len(numbers) - 1) + 1))
            if len(numbers) >= limit:
                break
        return numbers[:limit]

    def to_json(self) -> list[list[Any]]:
        return [
            [low, high, since, reported]
            for (low, high), since, reported in zip(
                self.gaps, self._since, self._reported, strict=True
            )
        ]


def subtract_windows(
    start: datetime, end: datetime, windows: list[tuple[datetime, datetime]]
) -> list[tuple[datetime, datetime]]:
    """The parts of `start`..`end` that lie outside every window, in order. An instant (start
    equals end) is kept unless a window covers it."""
    pieces = [(start, end)]
    for low, high in sorted(windows):
        kept: list[tuple[datetime, datetime]] = []
        for a, b in pieces:
            if b < low or a > high or (a == b and not low <= a <= high):
                kept.append((a, b))
                continue
            if a < low:
                kept.append((a, low))
            if b > high:
                kept.append((high, b))
        pieces = kept
    return pieces


def merge_episode(current: Mapping[str, Any], incoming: Normalised) -> dict[str, Any]:
    """The columns to set on a stored episode when `incoming` (the same `event` and
    `started_at`) arrives. A later phase wins; an earlier one only adds what is missing."""
    newer = PHASE_RANK.get(incoming.phase or "", -1) >= PHASE_RANK.get(current["phase"] or "", -1)
    durations = [d for d in (current["duration_ms"], incoming.duration_ms) if d is not None]
    confidences = [c for c in (current["confidence"], incoming.confidence) if c is not None]
    if newer:
        phase = incoming.phase or current["phase"]
        ongoing = incoming.ongoing and phase != "ended"
        details = {**current["details"], **incoming.details}
        duration = incoming.duration_ms if incoming.duration_ms is not None else None
        if duration is None and durations:
            duration = max(durations)
    else:
        phase = current["phase"]
        ongoing = current["ongoing"]
        details = {**incoming.details, **current["details"]}
        duration = max(durations) if durations else None
    return {
        "phase": phase,
        "ongoing": ongoing,
        "details": details,
        "duration_ms": duration,
        "confidence": max(confidences) if confidences else None,
        "last_seq": max(x for x in (current["last_seq"], incoming.seq) if x is not None),
    }
