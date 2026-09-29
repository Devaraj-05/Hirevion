"""Fixtures shared by every backend package's tests that need the real PostgreSQL and Valkey
(marked `db`).

Locally they use the `hirevion_test` database of `uv run hv up`; CI runs service containers.
The schema is rebuilt from the migrations once per test session.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from uuid import UUID

import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from hirevion_core.db.migrate import migrate
from hirevion_core.db.session import Database, create_database
from hirevion_core.ids import uuid7
from hirevion_core.settings import CoreSettings, load_core_settings

TEST_DATABASE = os.environ.get("HV_TEST_DATABASE", "hirevion_test")
# The Valkey logical database the tests own; it is flushed before each test that uses it.
TEST_VALKEY_DB = 15


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--live",
        action="store_true",
        help="also run the `live` tests, which call the real AI vendors (costs a few cents)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    # An explicit flag rather than `-m`, which a later `-m` on the command line would replace.
    if config.getoption("--live"):
        return
    skip = pytest.mark.skip(reason="calls the real AI vendors; run with --live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


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
async def valkey(core_settings: CoreSettings) -> AsyncIterator[Redis]:
    client = Redis.from_url(core_settings.valkey_url(TEST_VALKEY_DB), decode_responses=True)
    await client.flushdb()
    yield client
    await client.aclose()


@pytest.fixture
async def empty_outbox(admin_engine: AsyncEngine) -> None:
    """Relay tests count events, so they start from an empty outbox."""
    async with admin_engine.begin() as conn:
        await conn.execute(text("DELETE FROM outbox_events"))


@pytest.fixture
async def relay_db(core_settings: CoreSettings, migrated_database: str) -> AsyncIterator[Database]:
    db = create_database(core_settings, "relay", migrated_database)
    yield db
    await db.dispose()
