"""The AI provider layer (PRD §78 and §79, ADR-0011): six services behind one interface.

    ai = build_ai(load_ai_settings(), db)
    result = await ai.llm.complete(AiContext(org_id, "screening.rank", prompt_version="v3"),
                                   messages, RankingSchema)

Profiles: `dev` (Gemini + Deepgram), `production` (OpenAI + Deepgram), `mock` (no network).
Every call is budget-checked and recorded in `ai_invocations` with its usage and cost.
"""

from __future__ import annotations

from dataclasses import dataclass

from hirevion_core.ai.mock import (
    MockEmbeddings,
    MockLLM,
    MockOCR,
    MockSpeechToText,
    MockTextToSpeech,
    MockVision,
)
from hirevion_core.ai.prices import PriceBook
from hirevion_core.ai.recorder import Recorder
from hirevion_core.ai.settings import AiSettings
from hirevion_core.ai.types import (
    EmbeddingService,
    LLMService,
    OCRService,
    SpeechToTextService,
    TextToSpeechService,
    VisionService,
)
from hirevion_core.db.session import Database


@dataclass(frozen=True, slots=True)
class AiServices:
    llm: LLMService
    embeddings: EmbeddingService
    stt: SpeechToTextService
    tts: TextToSpeechService
    vision: VisionService
    ocr: OCRService


def build_ai(settings: AiSettings, db: Database, prices: PriceBook | None = None) -> AiServices:
    """The services for `settings.profile`, recording through `db` (the app role)."""
    recorder = Recorder(db, prices or PriceBook.load(), settings)
    if settings.profile == "mock":
        return AiServices(
            llm=MockLLM(recorder, settings),
            embeddings=MockEmbeddings(recorder, settings),
            stt=MockSpeechToText(recorder, settings),
            tts=MockTextToSpeech(recorder, settings),
            vision=MockVision(recorder, settings),
            ocr=MockOCR(recorder, settings),
        )
    raise NotImplementedError(f"the {settings.profile} profile's backends are not wired yet")


__all__ = ["AiServices", "build_ai"]
