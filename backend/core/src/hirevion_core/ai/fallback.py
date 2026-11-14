"""A second provider for the screening route (product-owner decision, 2026-11-14: "if OpenRouter
is not working then use Nemotron"; ADR-0034).

The primary serves every call. When it can't (`AiUnavailable`: out of credit, unreachable,
rate-limited or failing), the same call goes to the fallback, and the primary is skipped for a
cooldown, so a run of calls doesn't pay its refusal (or its timeout and retries) each time. A
refusal (a bad request, an answer that doesn't fit the schema, the budget) is not sent
elsewhere: it would fail or be refused there too, and moving it would hide a bug. Every attempt
is recorded in `ai_invocations`.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable, Sequence

from pydantic import BaseModel

from hirevion_core.ai.openai_compat import OpenAICompatible
from hirevion_core.ai.types import (
    AiContext,
    AiUnavailable,
    ChatMessage,
    LlmResult,
    OcrPage,
    Tier,
    VisionResult,
)

log = logging.getLogger(__name__)
# How long a primary that couldn't serve is skipped before it gets another chance.
COOLDOWN_SECONDS = 60.0


class Fallback:
    """Chat, vision and page reading on `primary`, then on `secondary` when it can't serve."""

    def __init__(
        self,
        primary: OpenAICompatible,
        secondary: OpenAICompatible,
        *,
        cooldown: float = COOLDOWN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.primary = primary
        self.secondary = secondary
        self._cooldown = cooldown
        self._clock = clock
        self._skip_primary_until = float("-inf")

    @property
    def parts(self) -> tuple[OpenAICompatible, OpenAICompatible]:
        """Its backends (closed by `AiServices.aclose`)."""
        return self.primary, self.secondary

    async def _either[R](
        self, ctx: AiContext, call: Callable[[OpenAICompatible], Awaitable[R]]
    ) -> R:
        if self._clock() < self._skip_primary_until:
            return await call(self.secondary)
        try:
            return await call(self.primary)
        except AiUnavailable as error:
            self._skip_primary_until = self._clock() + self._cooldown
            # The error names the provider and an HTTP status, never a body or a prompt.
            log.warning(
                "ai.fallback",
                extra={
                    "purpose": ctx.purpose,
                    "from_provider": self.primary.provider,
                    "to_provider": self.secondary.provider,
                    "reason": str(error),
                    "cooldown_seconds": self._cooldown,
                },
            )
            return await call(self.secondary)

    async def complete[T: BaseModel](
        self,
        ctx: AiContext,
        messages: Sequence[ChatMessage],
        schema: type[T],
        tier: Tier = "strong",
    ) -> LlmResult[T]:
        return await self._either(
            ctx, lambda backend: backend.complete(ctx, messages, schema, tier)
        )

    async def analyze[T: BaseModel](
        self, ctx: AiContext, image: bytes, content_type: str, instruction: str, schema: type[T]
    ) -> VisionResult[T]:
        return await self._either(
            ctx, lambda backend: backend.analyze(ctx, image, content_type, instruction, schema)
        )

    async def read_page(self, ctx: AiContext, image: bytes, content_type: str) -> OcrPage:
        return await self._either(ctx, lambda backend: backend.read_page(ctx, image, content_type))
