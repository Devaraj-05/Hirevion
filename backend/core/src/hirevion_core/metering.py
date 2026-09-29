"""Usage metering: every service records what it consumes, at the source (master plan §11).

Meters are dotted names such as `ai.llm.input_tokens` or `storage.bytes`; each keeps one unit.
The rows feed per-organisation budgets, the usage pages (SP-22) and the cost model.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.models import UsageEvent

_METER = re.compile(r"[a-z][a-z0-9_]*(\.[a-z0-9_]+)+")


async def record_usage(
    session: AsyncSession,
    organization_id: UUID,
    meter: str,
    quantity: Decimal,
    unit: str,
    source: str,
    attributes: Mapping[str, Any] | None = None,
    occurred_at: datetime | None = None,
) -> None:
    """Record `quantity` of `meter` in the caller's (tenant) transaction."""
    if not _METER.fullmatch(meter):
        raise ValueError(f"not a meter name: {meter!r}")
    if quantity < 0:
        raise ValueError("a usage quantity can't be negative")
    event = UsageEvent(
        organization_id=organization_id,
        meter=meter,
        quantity=quantity,
        unit=unit,
        source=source,
        attributes=dict(attributes or {}),
    )
    if occurred_at is not None:
        event.occurred_at = occurred_at
    session.add(event)
    await session.flush()


async def usage_totals(
    session: AsyncSession, organization_id: UUID, since: datetime, until: datetime
) -> dict[str, tuple[Decimal, str]]:
    """`{meter: (total, unit)}` for usage in `[since, until)`."""
    rows = await session.execute(
        select(UsageEvent.meter, UsageEvent.unit, func.sum(UsageEvent.quantity))
        .where(
            UsageEvent.organization_id == organization_id,
            UsageEvent.occurred_at >= since,
            UsageEvent.occurred_at < until,
        )
        .group_by(UsageEvent.meter, UsageEvent.unit)
    )
    return {meter: (Decimal(total), unit) for meter, unit, total in rows}
