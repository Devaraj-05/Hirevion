"""The acknowledgement after an answer plays from audio made when the interview starts, so the
first sound the candidate hears doesn't wait for speech synthesis (C8 live run, 2026-11-15)."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from livekit import rtc

from hirevion_interview_agent.acks import Acknowledgements


@dataclass
class Chunk:
    frame: rtc.AudioFrame


def frame(marker: int) -> rtc.AudioFrame:
    return rtc.AudioFrame(
        data=bytes([marker, 0]) * 240, sample_rate=24_000, num_channels=1, samples_per_channel=240
    )


class Stream:
    def __init__(self, frames: list[rtc.AudioFrame]) -> None:
        self._frames = frames

    async def __aenter__(self) -> "Stream":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def __aiter__(self) -> AsyncIterator[Chunk]:
        for item in self._frames:
            yield Chunk(item)


class Voice:
    """Stands in for the session's TTS: two frames per phrase, or a failure."""

    def __init__(self, failing: frozenset[str] = frozenset()) -> None:
        self.asked: list[str] = []
        self._failing = failing

    def synthesize(self, text: str) -> Stream:
        self.asked.append(text)
        if text in self._failing:
            raise RuntimeError("synthesis failed")
        marker = len(self.asked)
        return Stream([frame(marker), frame(marker + 100)])


async def played(audio: AsyncIterator[rtc.AudioFrame] | None) -> list[bytes]:
    assert audio is not None
    return [bytes(item.data) async for item in audio]


def test_prepared_acknowledgements_play_from_memory() -> None:
    async def scenario() -> None:
        acks = Acknowledgements(("Okay.", "Right."))
        voice = Voice()
        await acks.prepare(voice)  # type: ignore[arg-type]
        first = await played(acks.audio("Okay."))
        again = await played(acks.audio("Okay."))
        assert first == again == [bytes(frame(2).data), bytes(frame(102).data)]
        # Made once per phrase, then replayed: no synthesis on the turn itself. The first
        # answer's phrase (turn 1) is made first.
        assert voice.asked == ["Right.", "Okay."]

    asyncio.run(scenario())


def test_a_phrase_without_audio_is_synthesised_live() -> None:
    async def scenario() -> None:
        acks = Acknowledgements(("Okay.", "Right."))
        assert acks.audio("Okay.") is None  # not prepared yet
        await acks.prepare(Voice(failing=frozenset({"Right."})))  # type: ignore[arg-type]
        assert acks.audio("Right.") is None
        assert acks.audio("Okay.") is not None

    asyncio.run(scenario())


def test_the_phrases_take_turns() -> None:
    acks = Acknowledgements(("Okay.", "Right.", "I see."))
    picked: list[Any] = [acks.pick(turn) for turn in range(1, 5)]
    assert picked == ["Right.", "I see.", "Okay.", "Right."]
