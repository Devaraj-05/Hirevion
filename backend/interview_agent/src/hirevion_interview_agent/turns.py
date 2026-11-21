"""When the candidate's answer began and ended: from the first speech of the turn to its last
stop. Voice activity reports a pause mid-answer as speech stopping and starting again; the start
must stay where the answer began (the owner's run of 2026-11-21 stored each answer as only its
last stretch of speech, so answers looked short and their wait long; ADR-0047)."""

from __future__ import annotations

from datetime import datetime


class SpeechWindow:
    def __init__(self) -> None:
        self._started: datetime | None = None
        self._ended: datetime | None = None

    def speaking(self, now: datetime) -> None:
        if self._started is None:
            self._started = now
        self._ended = None  # still speaking: no end yet

    def stopped(self, now: datetime) -> None:
        if self._started is not None:  # a stop the last answer already counted is no one's
            self._ended = now

    def clear(self) -> None:
        """Drops speech no answer came from: a cough the recogniser left out, heard before the
        interviewer spoke again or in a turn with no words."""
        self._started = self._ended = None

    def take(self, now: datetime) -> tuple[datetime | None, datetime]:
        """The answer's start (None when no speech was heard) and end, and a fresh window."""
        window = (self._started, self._ended or now)
        self._started = self._ended = None
        return window
