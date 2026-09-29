"""Keyset pagination against PostgreSQL (as the admin role, which sees every organisation)."""

from collections.abc import AsyncIterator, Sequence
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from hirevion_api.pagination import PageParams, paginate
from hirevion_core.ids import uuid7
from hirevion_core.models import Organization

pytestmark = pytest.mark.db


@pytest.fixture
async def seven(admin_engine: AsyncEngine) -> tuple[str, list[UUID]]:
    """Seven organisations created in one transaction, so they share `created_at`."""
    prefix = f"page-{uuid7().hex[-8:]}-"
    ids = [uuid7() for _ in range(7)]
    async with admin_engine.begin() as conn:
        for number, org_id in enumerate(ids):
            await conn.execute(
                text("INSERT INTO organizations (id, name, slug) VALUES (:id, :name, :slug)"),
                {"id": org_id, "name": f"{prefix}{number}", "slug": f"{prefix}{number}"},
            )
    return prefix, ids


@pytest.fixture
async def session(admin_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with AsyncSession(admin_engine) as session:
        yield session


async def walk(
    session: AsyncSession,
    prefix: str,
    order_by: Sequence[InstrumentedAttribute[Any]],
    descending: bool = False,
) -> tuple[list[int], list[UUID]]:
    statement = select(Organization).where(Organization.name.like(f"{prefix}%"))
    sizes: list[int] = []
    seen: list[UUID] = []
    cursor: str | None = None
    while True:
        rows, cursor = await paginate(
            session, statement, order_by, PageParams(3, cursor), descending=descending
        )
        sizes.append(len(rows))
        seen += [row.id for row in rows]
        if cursor is None:
            return sizes, seen


async def test_pages_cover_every_row_once(
    session: AsyncSession, seven: tuple[str, list[UUID]]
) -> None:
    prefix, ids = seven
    assert await walk(session, prefix, [Organization.id]) == ([3, 3, 1], sorted(ids))


async def test_descending_pages_come_back_reversed(
    session: AsyncSession, seven: tuple[str, list[UUID]]
) -> None:
    prefix, ids = seven
    sizes, seen = await walk(session, prefix, [Organization.id], descending=True)
    assert seen == sorted(ids, reverse=True)
    assert sizes == [3, 3, 1]


async def test_ties_on_the_first_column_are_broken_by_id(
    session: AsyncSession, seven: tuple[str, list[UUID]]
) -> None:
    prefix, ids = seven
    _, seen = await walk(session, prefix, [Organization.created_at, Organization.id])
    assert seen == sorted(ids)
