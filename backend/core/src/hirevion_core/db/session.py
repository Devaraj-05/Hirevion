"""Database sessions that are always tenant-scoped (ADR-0009).

`tenant(org_id)` sets `app.org_id` with `set_config(..., true)`, which lasts only until the
transaction ends. A pooled connection therefore never carries one tenant's scope into the
next session, and `unscoped()` sees no tenant rows at all.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from hirevion_core.settings import CoreSettings, Role


class Database:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def tenant(self, organization_id: UUID) -> AsyncIterator[AsyncSession]:
        """A transaction that sees only `organization_id`'s rows; it commits on success."""
        async with self._sessions() as session, session.begin():
            await _set_tenant(session, organization_id)
            yield session

    @asynccontextmanager
    async def unscoped(self) -> AsyncIterator[AsyncSession]:
        """A transaction with no tenant: tenant tables look empty and refuse writes."""
        async with self._sessions() as session, session.begin():
            yield session

    async def dispose(self) -> None:
        await self.engine.dispose()


async def _set_tenant(session: AsyncSession, organization_id: UUID) -> None:
    await session.execute(
        text("SELECT set_config('app.org_id', :org, true)"),
        {"org": str(UUID(str(organization_id)))},
    )


async def switch_tenant(session: AsyncSession, organization_id: UUID) -> None:
    """Moves a `tenant()` transaction to another organisation, for platform actions that change
    one organisation and record it in the platform's audit chain atomically (ADR-0014). Pending
    changes are flushed first, while the tenant they belong to is still current."""
    await session.flush()
    await _set_tenant(session, organization_id)


def create_database(
    settings: CoreSettings, role: Role, database: str | None = None, **engine_options: Any
) -> Database:
    """A `Database` connected as `role` (`"app"` for services, `"relay"` for the outbox relay)."""
    engine = create_async_engine(
        settings.database_url(role, database), pool_pre_ping=True, **engine_options
    )
    return Database(engine)
