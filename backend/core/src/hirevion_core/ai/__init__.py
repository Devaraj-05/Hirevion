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
from hirevion_core.ai.deepgram import require_key as require_deepgram_key
from hirevion_core.ai.fallback import Fallback
from hirevion_core.ai.mock import (
    MockEmbeddings,
    MockLLM,
    MockOCR,
    MockSpeechToText,
    MockTextToSpeech,
    MockVision,
)
from hirevion_core.ai.openai_compat import OpenAICompatible, require_key
from hirevion_core.ai.prices import PriceBook
from hirevion_core.ai.recorder import Recorder
from hirevion_core.ai.routing import PurposeRouter
from hirevion_core.ai.settings import AiSettings, Provider
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

        def collect(service: object) -> None:
            # A router's parts may themselves have parts (a fallback).
            parts = getattr(service, "parts", None)
            if parts is None:
                backends.append(service)
            else:
                for part in parts:
                    collect(part)

        for service in (self.llm, self.embeddings, self.stt, self.tts, self.vision, self.ocr):
            collect(service)
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
        # Every key first: a client opened before a later key fails would never be closed.
        require_key(settings, "openai")
        require_deepgram_key(settings)
        compat = OpenAICompatible(settings, recorder, "openai")
        speech = Deepgram(settings, recorder)
        return AiServices(
            llm=compat, embeddings=compat, stt=speech, tts=speech, vision=compat, ocr=compat
        )
    # `dev` (ADR-0034): screening (with page reading) and interviews each go to their route's
    # provider; screening falls back to a second provider when its own can't serve; every
    # stored vector comes from the one embedding provider.
    first = settings.screening_provider
    choice = settings.screening_fallback
    fallback: Provider | None = None if choice == "none" or choice == first else choice
    wanted = [first, fallback, settings.interview_provider, settings.embedding_provider]
    used: list[Provider] = list(dict.fromkeys(p for p in wanted if p is not None))
    # Every key first: a client opened before a later key fails would never be closed.
    for provider in used:
        require_key(settings, provider)
    require_deepgram_key(settings)
    backends = {provider: OpenAICompatible(settings, recorder, provider) for provider in used}
    screening: Fallback | OpenAICompatible = (
        backends[first] if fallback is None else Fallback(backends[first], backends[fallback])
    )
    interview = backends[settings.interview_provider]
    chat: LLMService = screening if interview is screening else PurposeRouter(screening, interview)
    speech = Deepgram(settings, recorder)
    return AiServices(
        llm=chat,
        embeddings=backends[settings.embedding_provider],
        stt=speech,
        tts=speech,
        vision=screening,
        ocr=screening,
    )


__all__ = ["AiServices", "build_ai"]
