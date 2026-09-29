"""Fixtures for tests that need the real PostgreSQL and Valkey (marked `db`).

Locally they use the `hirevion_test` database of `uv run hv up`; CI runs service containers.
The schema is rebuilt from the migrations once per test session.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from hirevion_core.db.migrate import migrate
from hirevion_core.db.session import Database, create_database
from hirevion_core.ids import uuid7
from hirevion_core.settings import CoreSettings, load_core_settings

TEST_DATABASE = os.environ.get("HV_TEST_DATABASE", "hirevion_test")


async def _reset_schema(settings: CoreSettings, database: str) -> None:
    engine = create_async_engine(settings.database_url("admin", database))
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def core_settings() -> CoreSettings:
    return load_core_settings()


@pytest.fixture(scope="session")
def migrated_database(core_settings: CoreSettings) -> str:
    """The test database, reset and migrated once per session."""
    asyncio.run(_reset_schema(core_settings, TEST_DATABASE))
    asyncio.run(migrate(core_settings, TEST_DATABASE))
    return TEST_DATABASE


@pytest.fixture
async def admin_engine(
    core_settings: CoreSettings, migrated_database: str
) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(core_settings.database_url("admin", migrated_database))
    yield engine
    await engine.dispose()


@pytest.fixture
def make_organization(admin_engine: AsyncEngine) -> Callable[[str], Awaitable[UUID]]:
    """Creates an organisation as the admin role (the app role can't) and returns its id."""

    async def make(name: str) -> UUID:
        org_id = uuid7()
        async with admin_engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO organizations (id, name, slug) VALUES (:id, :name, :slug)"),
                {"id": org_id, "name": name, "slug": f"{name.lower()}-{org_id.hex[-12:]}"},
            )
        return org_id

    return make


@pytest.fixture
async def app_db(core_settings: CoreSettings, migrated_database: str) -> AsyncIterator[Database]:
    db = create_database(core_settings, "app", migrated_database)
    yield db
    await db.dispose()


@pytest.fixture
async def relay_db(core_settings: CoreSettings, migrated_database: str) -> AsyncIterator[Database]:
    db = create_database(core_settings, "relay", migrated_database)
    yield db
    await db.dispose()
