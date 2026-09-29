"""Alembic environment for the Hirevion database (async, asyncpg).

`hv migrate` (`hirevion_core.db.migrate`) hands over an open connection in
`config.attributes["connection"]`. Run from the `alembic` command line instead, this connects as
the admin role from the root `.env`; `-x database=NAME` picks another database.
"""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

import hirevion_core.models  # noqa: F401  (registers every table on Base.metadata)
from hirevion_core.db.base import Base
from hirevion_core.settings import load_core_settings

target_metadata = Base.metadata


def run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection, target_metadata=target_metadata, compare_server_default=True
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_standalone() -> None:
    database = context.get_x_argument(as_dictionary=True).get("database")
    url = load_core_settings().database_url("admin", database)
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline (--sql) mode isn't supported; run `uv run hv migrate`.")

shared = context.config.attributes.get("connection")
if shared is not None:
    run_migrations(shared)
else:
    asyncio.run(run_migrations_standalone())
