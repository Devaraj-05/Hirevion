"""Usage metering: every service records what it uses (master plan §11)."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from hirevion_core.db.session import Database
from hirevion_core.metering import record_usage, usage_totals

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]


async def test_usage_is_summed_per_meter_within_the_window(
    app_db: Database, make_organization: MakeOrganization
) -> None:
    org = await make_organization("Metered")
    now = datetime.now(UTC)
    async with app_db.tenant(org) as session:
        await record_usage(
            session, org, "ai.llm.input_tokens", Decimal(1200), "token", "screening.rank"
        )
        await record_usage(
            session, org, "ai.llm.input_tokens", Decimal(300), "token", "screening.rank"
        )
        await record_usage(
            session, org, "ai.stt.seconds", Decimal("12.5"), "second", "interview.turn"
        )
        await record_usage(
            session,
            org,
            "ai.stt.seconds",
            Decimal(99),
            "second",
            "interview.turn",
            occurred_at=now - timedelta(days=40),
        )

    async with app_db.tenant(org) as session:
        totals = await usage_totals(session, org, now - timedelta(days=1), now + timedelta(days=1))
    assert totals == {
        "ai.llm.input_tokens": (Decimal(1500), "token"),
        "ai.stt.seconds": (Decimal("12.5"), "second"),
    }


@pytest.mark.parametrize(("meter", "quantity"), [("Bad Meter", Decimal(1)), ("ai.ok", Decimal(-1))])
async def test_meters_and_quantities_are_checked(
    app_db: Database, make_organization: MakeOrganization, meter: str, quantity: Decimal
) -> None:
    org = await make_organization("MeterChecks")
    with pytest.raises(ValueError, match=r"meter|quantity"):
        async with app_db.tenant(org) as session:
            await record_usage(session, org, meter, quantity, "token", "test")
