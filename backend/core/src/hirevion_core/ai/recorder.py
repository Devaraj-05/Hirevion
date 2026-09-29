"""`Recorder`: the budget check and the record of every AI call (PRD §79, master plan §11).

Each call writes one `ai_invocations` row and its `usage_events` in a transaction of its own,
so money spent is recorded even when the caller's transaction later rolls back. A call is
refused before it reaches the vendor once the organisation's monthly AI spend has reached its
`ai.cost.usd` quota (or the configured default budget).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from opentelemetry import trace
from sqlalchemy import func, select

from hirevion_core.ai.prices import PriceBook
from hirevion_core.ai.settings import AiSettings
from hirevion_core.ai.types import AiBudgetExceeded, AiContext, AiError, Service, Usage
from hirevion_core.db.session import Database
from hirevion_core.metering import record_usage
from hirevion_core.models import AiInvocation, Quota

log = logging.getLogger(__name__)

AI_COST_METER = "ai.cost.usd"


def _trace_id() -> str | None:
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else None


def _meters(
    service: Service, usage: Usage, cost: Decimal | None
) -> Iterator[tuple[str, Decimal, str]]:
    if usage.input_tokens:
        yield f"ai.{service}.input_tokens", Decimal(usage.input_tokens), "token"
    if usage.output_tokens:
        yield f"ai.{service}.output_tokens", Decimal(usage.output_tokens), "token"
    if usage.audio_seconds:
        yield f"ai.{service}.seconds", usage.audio_seconds, "second"
    if usage.characters:
        yield f"ai.{service}.characters", Decimal(usage.characters), "character"
    if cost:
        yield AI_COST_METER, cost, "usd"


class Recorder:
    def __init__(self, db: Database, prices: PriceBook, settings: AiSettings) -> None:
        self.db = db
        self.prices = prices
        self.settings = settings

    async def ensure_budget(self, organization_id: UUID) -> None:
        """Raise `AiBudgetExceeded` once this month's AI spend reaches the organisation's limit."""
        month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        async with self.db.tenant(organization_id) as session:
            limit = await session.scalar(
                select(Quota.limit_value).where(
                    Quota.organization_id == organization_id,
                    Quota.meter == AI_COST_METER,
                    Quota.period == "month",
                )
            )
            spent = await session.scalar(
                select(func.coalesce(func.sum(AiInvocation.cost_usd), 0)).where(
                    AiInvocation.organization_id == organization_id,
                    AiInvocation.occurred_at >= month_start,
                )
            )
        budget = self.settings.monthly_budget_usd if limit is None else Decimal(limit)
        if Decimal(spent or 0) >= budget:
            raise AiBudgetExceeded(f"this month's AI budget of ${budget} is spent")

    async def call[R](
        self,
        ctx: AiContext,
        service: Service,
        provider: str,
        model: str,
        run: Callable[[], Awaitable[R]],
        usage: Callable[[R], Usage],
        output: Callable[[R], Any],
    ) -> R:
        """Check the budget, run the vendor call, and record it whether it worked or not."""
        await self.ensure_budget(ctx.organization_id)
        started = time.perf_counter()
        try:
            result = await run()
        except AiError as error:
            await self._record(
                ctx, service, provider, model, error.usage or Usage(), None, started, error.code
            )
            raise
        except Exception:
            await self._record(ctx, service, provider, model, Usage(), None, started, "internal")
            raise
        await self._record(
            ctx, service, provider, model, usage(result), output(result), started, None
        )
        return result

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
        cost = self.prices.cost(
            model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            seconds=usage.audio_seconds,
            characters=usage.characters,
            on=now.date(),
        )
        attributes: dict[str, Any] = {"model": model, "provider": provider}
        if usage.estimated:
            attributes["estimated"] = True
        try:
            async with self.db.tenant(ctx.organization_id) as session:
                session.add(
                    AiInvocation(
                        occurred_at=now,
                        organization_id=ctx.organization_id,
                        service=service,
                        purpose=ctx.purpose,
                        provider=provider,
                        model=model,
                        model_version=usage.model_version,
                        prompt_version=ctx.prompt_version,
                        rubric_version=ctx.rubric_version,
                        evaluation_version=ctx.evaluation_version,
                        input_refs=dict(ctx.input_refs),
                        output=output,
                        input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens,
                        audio_seconds=usage.audio_seconds,
                        characters=usage.characters,
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        cost_usd=cost,
                        status="ok" if error_code is None else "error",
                        error_code=error_code,
                        trace_id=_trace_id(),
                    )
                )
                for meter, quantity, unit in _meters(service, usage, cost):
                    await record_usage(
                        session, ctx.organization_id, meter, quantity, unit, ctx.purpose, attributes
                    )
        except Exception:
            # The vendor call already happened; losing its record must not also lose its result.
            log.exception("Recording an AI %s call for %s failed", service, ctx.purpose)
