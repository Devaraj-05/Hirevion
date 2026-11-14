"""A second provider for the screening route (product-owner decision, 2026-11-14: "if OpenRouter
is not working then use Nemotron"; ADR-0034).

The primary serves every call. When it can't (`AiUnavailable`: out of credit, unreachable,
rate-limited or failing), the same call goes to the fallback. A refusal (a bad request, an answer
that doesn't fit the schema, the organisation's budget) is not sent elsewhere: it would fail or be
refused there too, and moving it would hide a bug. Both attempts are recorded in `ai_invocations`.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

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


class Fallback:
    """Chat, vision and page reading on `primary`, then on `secondary` when it can't serve."""

    def __init__(self, primary: OpenAICompatible, secondary: OpenAICompatible) -> None:
        self.primary = primary
        self.secondary = secondary

    @property
    def parts(self) -> tuple[OpenAICompatible, OpenAICompatible]:
        """Its backends (closed by `AiServices.aclose`)."""
        return self.primary, self.secondary

    def _falling_back(self, ctx: AiContext, error: AiUnavailable) -> None:
        # The error names the provider and an HTTP status, never a body or a prompt.
        log.warning(
            "ai.fallback",
            extra={
                "purpose": ctx.purpose,
                "from_provider": self.primary.provider,
                "to_provider": self.secondary.provider,
                "reason": str(error),
            },
        )

    async def complete[T: BaseModel](
        self,
        ctx: AiContext,
        messages: Sequence[ChatMessage],
        schema: type[T],
        tier: Tier = "strong",
    ) -> LlmResult[T]:
        try:
            return await self.primary.complete(ctx, messages, schema, tier)
        except AiUnavailable as error:
            self._falling_back(ctx, error)
            return await self.secondary.complete(ctx, messages, schema, tier)

    async def analyze[T: BaseModel](
        self, ctx: AiContext, image: bytes, content_type: str, instruction: str, schema: type[T]
    ) -> VisionResult[T]:
        try:
            return await self.primary.analyze(ctx, image, content_type, instruction, schema)
        except AiUnavailable as error:
            self._falling_back(ctx, error)
            return await self.secondary.analyze(ctx, image, content_type, instruction, schema)

    async def read_page(self, ctx: AiContext, image: bytes, content_type: str) -> OcrPage:
        try:
            return await self.primary.read_page(ctx, image, content_type)
        except AiUnavailable as error:
            self._falling_back(ctx, error)
            return await self.secondary.read_page(ctx, image, content_type)
