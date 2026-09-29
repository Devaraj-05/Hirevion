"""`migrate()`: bring a database to the latest schema. `uv run hv migrate` runs it.

It creates or updates the application roles, applies the Alembic migrations, then creates
this month's and the next months' partitions. Everything runs in one transaction under an
advisory lock, so concurrent runs queue and a failed run leaves nothing half-applied.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from hirevion_core.db.partitions import (
    MONTHS_AHEAD,
    PARTITIONED_TABLES,
    ensure_monthly_partitions,
)
from hirevion_core.db.roles import bootstrap_roles
from hirevion_core.settings import CoreSettings

# backend/core/src/hirevion_core/db/migrate.py -> backend/migrations. Container images, which
# don't keep the repository layout, set HV_MIGRATIONS_DIR instead.
MIGRATIONS_DIR = Path(__file__).resolve().parents[4] / "migrations"
# The pg_advisory_xact_lock key every migrate() run takes ("hvmg").
MIGRATION_LOCK = 0x68766D67


def alembic_config() -> Config:
    override = os.environ.get("HV_MIGRATIONS_DIR")
    ini = (Path(override) if override else MIGRATIONS_DIR) / "alembic.ini"
    if not ini.exists():
        raise FileNotFoundError(f"the Alembic configuration is missing: {ini}")
    return Config(str(ini))


async def migrate(settings: CoreSettings, database: str | None = None) -> None:
    """Create the roles and apply every migration to `database` (default `POSTGRES_DB`)."""
    name = database or settings.postgres_db
    engine = create_async_engine(settings.database_url("admin", name), poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": MIGRATION_LOCK})
            await bootstrap_roles(
                conn,
                name,
                settings.postgres_app_password.get_secret_value(),
                settings.postgres_relay_password.get_secret_value(),
            )
            await conn.run_sync(_upgrade_to_head)
            today = datetime.now(UTC).date()
            for table in PARTITIONED_TABLES:
                await ensure_monthly_partitions(conn, table, today, MONTHS_AHEAD)
    finally:
        await engine.dispose()


def _upgrade_to_head(connection: Connection) -> None:
    config = alembic_config()
    # env.py uses this connection (and its open transaction) instead of connecting itself.
    config.attributes["connection"] = connection
    command.upgrade(config, "head")
