"""Another voice in the candidate's audio (C7-2; PRD §59, master plan §6.12 "detection of
additional speakers").

Deepgram's diarisation labels each final transcript with its main speaker (`S0`, `S1`, ...),
and streaming diarisation sometimes splits one voice in two for a moment. So:

- the candidate's voice is the label with the most words over the first `WARMUP_WORDS` words
  (not merely the first label heard, which could be the interviewer's voice leaking back);
- another label is flagged only when it persists: at least `OTHER_MIN_FINALS` transcripts and
  `OTHER_MIN_WORDS` words within `WINDOW_SECONDS`, and at most once every `COOLDOWN_SECONDS`;
- and only while the candidate's own label is heard too: a new label talking alone, with the
  candidate's silent for the window, is the candidate relabelled (Deepgram numbers speakers per
  connection, and the plugin reconnects mid-interview), so it becomes the candidate's.

Only the count of voices and words is recorded, never the words. It is a signal, never proof: a
TV, a relative passing by, or the interviewer's voice past echo cancellation can be another
voice (review, 2026-11-26).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

WARMUP_WORDS = 20
OTHER_MIN_FINALS = 2
OTHER_MIN_WORDS = 8
WINDOW_SECONDS = 60.0
COOLDOWN_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class Heard:
    at: float
    speakers: int
    """Voices heard so far, the candidate's included."""
    words: int
    """The other voices' words in the window that raised it."""


class VoiceWatch:
    def __init__(self) -> None:
        self._warmup: Counter[str] = Counter()
        self._candidate: str | None = None
        self._voices: set[str] = set()
        self._recent: list[tuple[float, str, int]] = []
        self._last: float | None = None
        self._candidate_at: float | None = None

    @property
    def candidate(self) -> str | None:
        return self._candidate

    def heard(self, speaker: str | None, transcript: str, *, at: float) -> Heard | None:
        words = len(transcript.split())
        if speaker is None or words == 0:
            return None
        if self._candidate is None:
            self._warmup[speaker] += words
            if sum(self._warmup.values()) >= WARMUP_WORDS:
                self._candidate = self._warmup.most_common(1)[0][0]
                self._voices = {self._candidate}
                self._candidate_at = at
            return None
        if speaker == self._candidate:
            self._candidate_at = at
            return None
        self._voices.add(speaker)
        self._recent = [entry for entry in self._recent if at - entry[0] < WINDOW_SECONDS]
        self._recent.append((at, speaker, words))
        said = sum(entry[2] for entry in self._recent)
        if len(self._recent) < OTHER_MIN_FINALS or said < OTHER_MIN_WORDS:
            return None
        if self._candidate_at is None or at - self._candidate_at >= WINDOW_SECONDS:
            # Only the new label talks: the candidate, relabelled after a reconnect.
            self._candidate, self._candidate_at, self._recent = speaker, at, []
            return None
        if self._last is not None and at - self._last < COOLDOWN_SECONDS:
            return None
        self._last = at
        self._recent = []
        return Heard(at, len(self._voices), said)
