"""Usage events: the metering source of truth (master plan §11), tenant-scoped and partitioned."""

from collections.abc import Awaitable, Callable
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.db.session import Database
from hirevion_core.models import UsageEvent

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]


def tokens(org: UUID, quantity: str) -> UsageEvent:
    return UsageEvent(
        organization_id=org,
        meter="llm.tokens.input",
        quantity=Decimal(quantity),
        unit="token",
        source="interview-agent",
        attributes={"model": "gemini-3.1-flash-lite"},
    )


async def test_usage_is_recorded_and_tenant_scoped(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    acme = await make_organization("UsageAcme")
    globex = await make_organization("UsageGlobex")
    async with app_db.tenant(acme) as session:
        session.add_all([tokens(acme, "1200"), tokens(acme, "0.5")])

    async with app_db.tenant(acme) as session:
        quantities = await session.scalars(select(UsageEvent.quantity))
        assert sorted(quantities.all()) == [Decimal("0.5"), Decimal("1200")]
    async with app_db.tenant(globex) as session:
        rows = await session.scalars(
            select(UsageEvent.id).where(UsageEvent.organization_id == acme)
        )
        assert rows.all() == []

    async with admin_engine.connect() as conn:
        partitions = await conn.scalars(
            text(
                "SELECT DISTINCT tableoid::regclass::text FROM usage_events "
                "WHERE organization_id = :org"
            ),
            {"org": acme},
        )
        assert [name.startswith("usage_events_y") for name in partitions] == [True]


async def test_usage_cannot_be_changed_by_the_app_role(
    app_db: Database, make_organization: MakeOrganization
) -> None:
    org = await make_organization("UsageLocked")
    async with app_db.tenant(org) as session:
        session.add(tokens(org, "10"))
    with pytest.raises(DBAPIError, match="permission denied"):
        async with app_db.tenant(org) as session:
            await session.execute(text("UPDATE usage_events SET quantity = 0"))
