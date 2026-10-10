"""An LLM that needs no database: the mock profile (or a real vendor) with its calls kept in
memory instead of `ai_invocations`.

The eval harness and the unit tests use it. The calls are recorded like the real thing (the §79
fields, tokens, latency, cost), so what an evaluation would store can be checked without a
database, and the harness can report its own spend.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from hirevion_core.ai.mock import MOCK_PRICES, MockLLM
from hirevion_core.ai.recorder import Recorder
from hirevion_core.ai.settings import AiSettings
from hirevion_core.ai.types import AiContext, Service, Usage
from hirevion_core.db.session import Database


class MemoryRecorder(Recorder):
    """A `Recorder` with no budget check and no database: `rows` holds what would be stored."""

    def __init__(self, settings: AiSettings | None = None) -> None:
        settings = settings or AiSettings(profile="mock")  # type: ignore[call-arg]
        super().__init__(cast(Database, None), MOCK_PRICES, settings)
        self.rows: list[dict[str, Any]] = []

    async def ensure_budget(self, organization_id: Any) -> None:
        return None

    async def _record(
        self,
        ctx: AiContext,
        service: Service,
        provider: str,
        model: str,
        usage: Usage,
        output: Any,
        started: float,
        error_code: str | None,
    ) -> None:
        now = datetime.now(UTC)
        self.rows.append(
            {
                "occurred_at": now,
                "organization_id": ctx.organization_id,
                "service": service,
                "purpose": ctx.purpose,
                "provider": provider,
                "model": model,
                "model_version": usage.model_version,
                "prompt_version": ctx.prompt_version,
                "rubric_version": ctx.rubric_version,
                "evaluation_version": ctx.evaluation_version,
                "input_refs": dict(ctx.input_refs),
                "output": output,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cost_usd": self.prices.cost(
                    model,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    seconds=usage.audio_seconds,
                    characters=usage.characters,
                    on=now.date(),
                )
                or Decimal(0),
                "status": "ok" if error_code is None else "error",
                "error_code": error_code,
            }
        )


def offline_llm(settings: AiSettings | None = None) -> tuple[MockLLM, MemoryRecorder]:
    """The mock LLM with its recorder; scripts and failures can be set on the mock."""
    recorder = MemoryRecorder(settings)
    return MockLLM(recorder, recorder.settings), recorder
