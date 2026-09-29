"""The ORM models and the hand-written migrations describe the same schema.

RLS policies, grants, triggers and partitions exist only in the migrations, so the comparison
leaves them out: autogenerate doesn't see the first three, and partitions are skipped here.
"""

from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

import hirevion_core.models  # noqa: F401  (registers every table)
from hirevion_core.db.base import Base
from hirevion_core.db.partitions import PARTITIONED_TABLES

pytestmark = pytest.mark.db

_PARTITION_PREFIXES = tuple(f"{table}_" for table in PARTITIONED_TABLES)


def _include(obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any) -> bool:
    if type_ == "table" and name is not None and name.startswith(_PARTITION_PREFIXES):
        return False
    return not (type_ == "table" and name == "alembic_version")


def _differences(connection: Connection) -> list[Any]:
    context = MigrationContext.configure(
        connection,
        opts={"compare_type": True, "compare_server_default": True, "include_object": _include},
    )
    return list(compare_metadata(context, Base.metadata))


async def test_models_match_the_migrated_schema(admin_engine: AsyncEngine) -> None:
    async with admin_engine.connect() as conn:
        assert await conn.run_sync(_differences) == []
