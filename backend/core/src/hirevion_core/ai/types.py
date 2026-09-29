"""The AI provider layer's vocabulary: call context, results, errors and the six services.

PRD §78 names five services (LLM, embeddings, speech-to-text, text-to-speech, vision); OCR is the
sixth, for scanned resumes (master plan §5.3). Every implementation records each call through
`Recorder` (PRD §79).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal, Protocol, TypedDict
from uuid import UUID

from pydantic import BaseModel

Service = Literal["llm", "embedding", "stt", "tts", "vision", "ocr"]
Tier = Literal["fast", "strong"]
_PURPOSE = re.compile(r"[a-z][a-z0-9_.-]{0,63}")


class ChatMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class AiContext:
    """Who a call is for and why: the §79 governance fields that aren't about the model."""

    organization_id: UUID
    purpose: str  # what the call is for, e.g. "screening.rank"; also the usage `source`
    prompt_version: str | None = None
    rubric_version: str | None = None
    evaluation_version: str | None = None
    input_refs: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _PURPOSE.fullmatch(self.purpose):
            raise ValueError(f"not a purpose name (lower-case, dotted): {self.purpose!r}")


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    audio_seconds: Decimal = Decimal(0)
    characters: int = 0
    model_version: str | None = None
    # True when the vendor didn't report usage and it was estimated (e.g. Gemini embeddings).
    estimated: bool = False


class AiError(Exception):
    code = "error"

    def __init__(self, message: str, usage: Usage | None = None) -> None:
        super().__init__(message)
        self.usage = usage


class AiUnavailable(AiError):
    """The vendor is down, slow or rate-limiting; retrying later may work."""

    code = "unavailable"


class AiRequestError(AiError):
    """The vendor refused the request (bad input, bad key); retrying won't help."""

    code = "request_rejected"


class AiOutputInvalid(AiError):
    """The model's answer didn't match the requested schema, even after one repair."""

    code = "invalid_output"


class AiBudgetExceeded(AiError):
    """The organisation's monthly AI budget is spent; nothing was sent to the vendor."""

    code = "budget_exceeded"


@dataclass(frozen=True, slots=True)
class LlmResult[T]:
    value: T
    model: str
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True, slots=True)
class Embeddings:
    vectors: list[list[float]]
    model: str
    input_tokens: int


@dataclass(frozen=True, slots=True)
class Word:
    text: str
    start: float
    end: float
    confidence: float


@dataclass(frozen=True, slots=True)
class Transcript:
    text: str
    words: list[Word]
    duration_seconds: float
    model: str


@dataclass(frozen=True, slots=True)
class SpeechAudio:
    audio: bytes
    content_type: str
    characters: int
    model: str


@dataclass(frozen=True, slots=True)
class VisionResult[T]:
    value: T
    model: str
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True, slots=True)
class OcrPage:
    text: str
    confidence: float
    model: str


class LLMService(Protocol):
    async def complete[T: BaseModel](
        self,
        ctx: AiContext,
        messages: Sequence[ChatMessage],
        schema: type[T],
        tier: Tier = "strong",
    ) -> LlmResult[T]: ...


class EmbeddingService(Protocol):
    async def embed(self, ctx: AiContext, texts: Sequence[str]) -> Embeddings: ...


class SpeechToTextService(Protocol):
    async def transcribe(
        self, ctx: AiContext, audio: bytes, content_type: str, keyterms: Sequence[str] = ()
    ) -> Transcript: ...


class TextToSpeechService(Protocol):
    async def synthesize(self, ctx: AiContext, text: str) -> SpeechAudio: ...


class VisionService(Protocol):
    async def analyze[T: BaseModel](
        self, ctx: AiContext, image: bytes, content_type: str, instruction: str, schema: type[T]
    ) -> VisionResult[T]: ...


class OCRService(Protocol):
    async def read_page(self, ctx: AiContext, image: bytes, content_type: str) -> OcrPage: ...
