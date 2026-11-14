"""Which provider serves which AI task (ADR-0034, owner decision 2026-11-14).

In the `dev` profile the screening route (job descriptions, resumes, screening, with their
embeddings and page reading) goes to OpenRouter, and the interview route (questions, the live
interview, evaluation) goes to NVIDIA Nemotron. A call's route comes from the area of its
purpose (`AiContext.purpose`, e.g. "screening.rank" → screening). A purpose with no route is
refused, so a new task has to be given a provider before it ships.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel

from hirevion_core.ai.types import AiContext, ChatMessage, LlmResult, LLMService, Tier

Route = Literal["screening", "interview"]
SCREENING: Route = "screening"
INTERVIEW: Route = "interview"

_ROUTES: dict[str, Route] = {
    "jd": SCREENING,
    "job": SCREENING,
    "resume": SCREENING,
    "screening": SCREENING,
    "questions": INTERVIEW,
    "interview": INTERVIEW,
    "evaluation": INTERVIEW,
}


def route_for(purpose: str) -> Route:
    """The route of a purpose, from its area (the part before the first dot)."""
    try:
        return _ROUTES[purpose.split(".", 1)[0]]
    except KeyError:
        raise ValueError(
            f"no AI route for the purpose {purpose!r}: give its area a route in "
            "hirevion_core.ai.routing"
        ) from None


class PurposeRouter:
    """An LLM service that hands each call to the provider its purpose's route names."""

    def __init__(self, screening: LLMService, interview: LLMService) -> None:
        self.screening = screening
        self.interview = interview

    @property
    def parts(self) -> tuple[LLMService, LLMService]:
        """The services it routes to (closed by `AiServices.aclose`)."""
        return self.screening, self.interview

    async def complete[T: BaseModel](
        self,
        ctx: AiContext,
        messages: Sequence[ChatMessage],
        schema: type[T],
        tier: Tier = "strong",
    ) -> LlmResult[T]:
        target = self.screening if route_for(ctx.purpose) == SCREENING else self.interview
        return await target.complete(ctx, messages, schema, tier)
