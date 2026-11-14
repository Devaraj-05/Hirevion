"""The screening route's fallback (ADR-0034): a primary that can't serve is skipped for a
cooldown, so a run of calls doesn't pay its refusal (or its timeout) every time."""

from typing import Any
from uuid import UUID

import pytest
from pydantic import BaseModel

from hirevion_core.ai.fallback import Fallback
from hirevion_core.ai.types import AiContext, AiRequestError, AiUnavailable, LlmResult

ORG = UUID("00000000-0000-7000-8000-000000000001")


class Answer(BaseModel):
    ok: bool


class Backend:
    def __init__(self, provider: str, failure: Exception | None = None) -> None:
        self.provider = provider
        self.failure = failure
        self.calls = 0

    async def complete(
        self, ctx: AiContext, messages: Any, schema: type[Answer], tier: str = "strong"
    ) -> LlmResult[Answer]:
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        return LlmResult(Answer(ok=True), self.provider, 1, 1)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def ask(fallback: Fallback) -> str:
    result = await fallback.complete(AiContext(ORG, "screening.assess"), [], Answer)
    return result.model


async def test_a_primary_that_cannot_serve_is_skipped_for_the_cooldown() -> None:
    primary = Backend("openrouter", AiUnavailable("openrouter needs credit (402)"))
    secondary = Backend("nemotron")
    clock = Clock()
    fallback = Fallback(primary, secondary, cooldown=60.0, clock=clock)  # type: ignore[arg-type]

    assert await ask(fallback) == "nemotron"
    assert (primary.calls, secondary.calls) == (1, 1)
    # Within the cooldown the primary isn't asked again.
    clock.now += 59
    assert await ask(fallback) == "nemotron"
    assert (primary.calls, secondary.calls) == (1, 2)
    # After it, the primary gets another chance (credit may have been added).
    clock.now += 2
    primary.failure = None
    assert await ask(fallback) == "openrouter"
    assert (primary.calls, secondary.calls) == (2, 2)


async def test_a_refusal_neither_falls_back_nor_starts_the_cooldown() -> None:
    primary = Backend("openrouter", AiRequestError("openrouter refused the request (400)"))
    secondary = Backend("nemotron")
    fallback = Fallback(primary, secondary, cooldown=60.0, clock=Clock())  # type: ignore[arg-type]
    for _ in range(2):
        with pytest.raises(AiRequestError):
            await ask(fallback)
    assert (primary.calls, secondary.calls) == (2, 0)
