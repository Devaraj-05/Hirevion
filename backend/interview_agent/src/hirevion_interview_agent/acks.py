"""The short acknowledgement after an answer, played from audio made when the interview starts.

The acknowledgement is the first sound the candidate hears after an answer (master plan §6.8's
latency path). Synthesising it on the turn took 0.8 to 1.8 s on 2026-11-15, half of the turn's
latency, so each phrase is synthesised once and replayed. A phrase whose synthesis failed, or
isn't ready yet, is spoken through the TTS as before.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any

from livekit import rtc
from livekit.agents import tts

from hirevion_core.engine.guardrails import classify

log = logging.getLogger(__name__)

# Neutral: the interviewer notes that it heard the answer, never whether it was correct
# ("Right." told the owner his answer was right, 2026-11-21).
ACKNOWLEDGEMENTS = ("Thank you.", "Okay, thank you.", "Thanks.", "Noted.")


def acknowledges(text: str) -> bool:
    """Whether `text` gets an acknowledgement: only an answer does. A request ("repeat that", "I
    need a moment") or silence goes straight to the engine, which replies at once anyway."""
    return classify(text) == "answer"


class Acknowledgements:
    def __init__(self, phrases: Sequence[str] = ACKNOWLEDGEMENTS) -> None:
        self.phrases = tuple(phrases)
        self._audio: dict[str, list[rtc.AudioFrame]] = {}

    async def prepare(self, voice: tts.TTS[Any]) -> None:
        """Synthesise every phrase once with the interview's voice, the first one needed first."""
        for turn in range(1, len(self.phrases) + 1):
            phrase = self.pick(turn)
            try:
                async with voice.synthesize(phrase) as stream:
                    frames = [event.frame async for event in stream]
            except Exception as error:  # the phrase is synthesised live instead
                log.warning("Acknowledgement %r wasn't prepared: %s", phrase, error)
                continue
            if frames:
                self._audio[phrase] = frames

    def pick(self, turn: int) -> str:
        return self.phrases[turn % len(self.phrases)]

    def audio(self, phrase: str) -> AsyncIterator[rtc.AudioFrame] | None:
        """The phrase's prepared audio, or None to synthesise it live."""
        frames = self._audio.get(phrase)
        if frames is None:
            return None

        async def play() -> AsyncIterator[rtc.AudioFrame]:
            for frame in frames:
                yield frame

        return play()
