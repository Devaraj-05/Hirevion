"""The AI provider layer (PRD §78 and §79, ADR-0011): six services behind one interface.

    ai = build_ai(load_ai_settings(), db)
    result = await ai.llm.complete(AiContext(org_id, "screening.rank", prompt_version="v3"),
                                   messages, RankingSchema)

Profiles: `dev` (OpenRouter for screening, NVIDIA Nemotron for interviews, Deepgram for speech;
ADR-0034), `production` (OpenAI + Deepgram), `mock` (no network).
Every call is budget-checked and recorded in `ai_invocations` with its usage and cost.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from hirevion_core.ai.deepgram import Deepgram
from hirevion_core.ai.mock import (
    MockEmbeddings,
    MockLLM,
    MockOCR,
    MockSpeechToText,
    MockTextToSpeech,
    MockVision,
)
from hirevion_core.ai.openai_compat import OpenAICompatible
from hirevion_core.ai.prices import PriceBook
from hirevion_core.ai.recorder import Recorder
from hirevion_core.ai.routing import PurposeRouter
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

    async def aclose(self) -> None:
        """Close the vendor connections (each backend once, however many services it serves;
        a router's backends count as its own)."""
        seen: set[int] = set()
        backends: list[object] = []
        for service in (self.llm, self.embeddings, self.stt, self.tts, self.vision, self.ocr):
            backends.extend(getattr(service, "parts", (service,)))
        for backend in backends:
            close = getattr(backend, "aclose", None)
            if close is not None and id(backend) not in seen:
                seen.add(id(backend))
                await close()


def build_ai(settings: AiSettings, db: Database, prices: PriceBook | None = None) -> AiServices:
    """The services for `settings.profile`, recording through `db` (the app role)."""
    recorder = Recorder(db, prices or PriceBook.load(), settings)
    if settings.profile == "mock":
        llm = MockLLM(recorder, settings)
        if settings.mock_scripts is not None:
            llm.scripted.update(json.loads(settings.mock_scripts.read_text(encoding="utf-8")))
        return AiServices(
            llm=llm,
            embeddings=MockEmbeddings(recorder, settings),
            stt=MockSpeechToText(recorder, settings),
            tts=MockTextToSpeech(recorder, settings),
            vision=MockVision(recorder, settings),
            ocr=MockOCR(recorder, settings),
        )
    if settings.profile == "production":
        compat = OpenAICompatible(settings, recorder, "openai")
        speech = Deepgram(settings, recorder)
        return AiServices(
            llm=compat, embeddings=compat, stt=speech, tts=speech, vision=compat, ocr=compat
        )
    # `dev`: screening (with its embeddings and page reading) and interviews each go to their
    # route's provider (ADR-0034).
    screening = OpenAICompatible(settings, recorder, settings.screening_provider)
    interview = (
        screening
        if settings.interview_provider == settings.screening_provider
        else OpenAICompatible(settings, recorder, settings.interview_provider)
    )
    chat: LLMService = screening if interview is screening else PurposeRouter(screening, interview)
    speech = Deepgram(settings, recorder)
    return AiServices(
        llm=chat, embeddings=screening, stt=speech, tts=speech, vision=screening, ocr=screening
    )


__all__ = ["AiServices", "build_ai"]
