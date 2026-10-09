"""Deterministic services for CI and load tests: no network, stable outputs, realistic usage.

Each mock goes through `Recorder` like a real backend, so recording, metering and budgets are
tested exactly as they run in production. `failures` makes the next calls fail; `scripted`
returns a fixed value per purpose (for schemas the generic faker can't satisfy), or for the LLM
a function of the messages. A module whose purpose needs a realistic answer in every mock run (the
interview engine's analysis, SP-09) registers a deterministic responder with `respond_with`;
`scripted` still wins over it.
"""

from __future__ import annotations

import hashlib
import io
import math
import types
import wave
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal, Union, get_args, get_origin
from uuid import UUID

from pydantic import BaseModel

from hirevion_core.ai.prices import PriceBook
from hirevion_core.ai.recorder import Recorder
from hirevion_core.ai.settings import AiSettings
from hirevion_core.ai.types import (
    AiContext,
    AiError,
    ChatMessage,
    Embeddings,
    LlmResult,
    OcrPage,
    SpeechAudio,
    Tier,
    Transcript,
    Usage,
    VisionResult,
    Word,
)

PROVIDER = "mock"
# Priced so tests can check cost arithmetic end to end.
MOCK_PRICES = PriceBook(
    {
        "mock-llm": {"input_per_million_tokens": "1", "output_per_million_tokens": "2"},
        "mock-embedding": {"input_per_million_tokens": "0.1"},
        "mock-stt": {"per_minute": "0.01"},
        "mock-tts": {"per_thousand_characters": "0.03"},
        "mock-vision": {"input_per_million_tokens": "1", "output_per_million_tokens": "2"},
    }
)
# Deterministic LLM answers by purpose, from the messages (see `respond_with`).
RESPONDERS: dict[str, Callable[[Sequence[ChatMessage]], Any]] = {}
_PCM_BYTES_PER_SECOND = 32_000  # 16 kHz, 16-bit mono
_SPEECH_CHARS_PER_SECOND = 15


def respond_with(purpose: str, responder: Callable[[Sequence[ChatMessage]], Any]) -> None:
    """Makes the mock LLM answer `purpose` with `responder(messages)` instead of a generic fake."""
    RESPONDERS[purpose] = responder


def fake_vector(text: str, dimensions: int) -> list[float]:
    """A unit vector derived from `text` alone, so equal texts embed equally."""
    values: list[float] = []
    counter = 0
    while len(values) < dimensions:
        digest = hashlib.sha256(f"{counter}:{text}".encode()).digest()
        values.extend((byte - 127.5) / 127.5 for byte in digest)
        counter += 1
    values = values[:dimensions]
    norm = math.sqrt(sum(value * value for value in values))
    return [value / norm for value in values]


def _fake(annotation: Any) -> Any:
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (Union, types.UnionType):
        return None if type(None) in args else _fake(args[0])
    if origin is Literal:
        return args[0]
    if origin in (list, Sequence, set, frozenset, tuple):
        return []
    if origin is dict:
        return {}
    simple: dict[Any, Any] = {
        str: "mock",
        int: 1,
        float: 0.5,
        bool: True,
        Decimal: Decimal("1"),
        UUID: UUID(int=1),
        datetime: datetime(2026, 1, 1, tzinfo=UTC),
        date: date(2026, 1, 1),
    }
    if annotation in simple:
        return simple[annotation]
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return next(iter(annotation))
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return fake_instance(annotation).model_dump()
    raise TypeError(f"the mock can't fake {annotation!r}; script a value for this purpose")


def fake_instance[T: BaseModel](schema: type[T]) -> T:
    """The same valid instance of `schema` every time (defaults kept, required fields faked)."""
    values = {
        name: _fake(field.annotation)
        for name, field in schema.model_fields.items()
        if field.is_required()
    }
    return schema.model_validate(values)


def _silent_wav(seconds: float) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(b"\x00\x00" * int(16_000 * seconds))
    return buffer.getvalue()


class _Mock:
    def __init__(self, recorder: Recorder, settings: AiSettings) -> None:
        self.recorder = recorder
        self.settings = settings
        self.failures: list[AiError] = []
        self.scripted: dict[str, Any] = {}
        self.calls = 0

    def _begin(self) -> None:
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)


class MockLLM(_Mock):
    async def complete[T: BaseModel](
        self,
        ctx: AiContext,
        messages: Sequence[ChatMessage],
        schema: type[T],
        tier: Tier = "strong",
    ) -> LlmResult[T]:
        model = "mock-llm"

        async def run() -> LlmResult[T]:
            self._begin()
            scripted = self.scripted.get(ctx.purpose, RESPONDERS.get(ctx.purpose))
            if callable(scripted):  # an answer that depends on what was asked
                scripted = scripted(messages)
            value = (
                schema.model_validate(scripted) if scripted is not None else fake_instance(schema)
            )
            prompt = sum(len(message["content"]) for message in messages)
            answer = len(value.model_dump_json())
            return LlmResult(value, model, max(1, prompt // 4), max(1, answer // 4))

        return await self.recorder.call(
            ctx,
            "llm",
            PROVIDER,
            model,
            run,
            lambda r: Usage(r.input_tokens, r.output_tokens, model_version=r.model),
            lambda r: r.value.model_dump(mode="json"),
        )


class MockEmbeddings(_Mock):
    async def embed(self, ctx: AiContext, texts: Sequence[str]) -> Embeddings:
        model, dimensions = "mock-embedding", self.settings.embedding_dimensions

        async def run() -> Embeddings:
            self._begin()
            vectors = [fake_vector(text, dimensions) for text in texts]
            return Embeddings(vectors, model, max(1, sum(len(text) for text in texts) // 4))

        return await self.recorder.call(
            ctx,
            "embedding",
            PROVIDER,
            model,
            run,
            lambda r: Usage(input_tokens=r.input_tokens, model_version=r.model),
            lambda r: {"dimensions": dimensions, "count": len(r.vectors)},
        )


class MockSpeechToText(_Mock):
    async def transcribe(
        self, ctx: AiContext, audio: bytes, content_type: str, keyterms: Sequence[str] = ()
    ) -> Transcript:
        model = "mock-stt"

        async def run() -> Transcript:
            self._begin()
            text = str(self.scripted.get(ctx.purpose, "This is a mock transcript."))
            duration = len(audio) / _PCM_BYTES_PER_SECOND
            tokens = text.split()
            step = duration / max(len(tokens), 1)
            words = [
                Word(token, round(i * step, 3), round((i + 1) * step, 3), 0.99)
                for i, token in enumerate(tokens)
            ]
            return Transcript(text, words, duration, model)

        return await self.recorder.call(
            ctx,
            "stt",
            PROVIDER,
            model,
            run,
            lambda r: Usage(audio_seconds=Decimal(str(r.duration_seconds)), model_version=r.model),
            lambda r: {"text": r.text},
        )


class MockTextToSpeech(_Mock):
    async def synthesize(self, ctx: AiContext, text: str) -> SpeechAudio:
        model = "mock-tts"

        async def run() -> SpeechAudio:
            self._begin()
            audio = _silent_wav(len(text) / _SPEECH_CHARS_PER_SECOND)
            return SpeechAudio(audio, "audio/wav", len(text), model)

        return await self.recorder.call(
            ctx,
            "tts",
            PROVIDER,
            model,
            run,
            lambda r: Usage(characters=r.characters, model_version=r.model),
            lambda r: {"characters": r.characters},
        )


class MockVision(_Mock):
    async def analyze[T: BaseModel](
        self, ctx: AiContext, image: bytes, content_type: str, instruction: str, schema: type[T]
    ) -> VisionResult[T]:
        model = "mock-vision"

        async def run() -> VisionResult[T]:
            self._begin()
            scripted = self.scripted.get(ctx.purpose)
            value = (
                schema.model_validate(scripted) if scripted is not None else fake_instance(schema)
            )
            tokens_in = max(1, len(image) // 100 + len(instruction) // 4)
            return VisionResult(value, model, tokens_in, max(1, len(value.model_dump_json()) // 4))

        return await self.recorder.call(
            ctx,
            "vision",
            PROVIDER,
            model,
            run,
            lambda r: Usage(r.input_tokens, r.output_tokens, model_version=r.model),
            lambda r: r.value.model_dump(mode="json"),
        )


class MockOCR(_Mock):
    async def read_page(self, ctx: AiContext, image: bytes, content_type: str) -> OcrPage:
        model = "mock-vision"

        async def run() -> OcrPage:
            self._begin()
            return OcrPage(str(self.scripted.get(ctx.purpose, "Mock page text.")), 0.99, model)

        return await self.recorder.call(
            ctx,
            "ocr",
            PROVIDER,
            model,
            run,
            lambda r: Usage(input_tokens=max(1, len(image) // 100), model_version=r.model),
            lambda r: {"characters": len(r.text), "confidence": r.confidence},
        )
