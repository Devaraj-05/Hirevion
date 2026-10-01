"""The resource scope: organisation-wide, or limited to one's teams' work and one's own
(the product owner's "organisation-wide, optional team limit"; ADR-0014)."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import String, Uuid, column, select, text, values
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.access.scope import resource_scope, scope_clause
from hirevion_core.db.session import Database
from hirevion_core.ids import uuid7

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]


async def team(
    engine: AsyncEngine, organization_id: UUID, name: str, members: list[UUID], archived: bool
) -> UUID:
    team_id = uuid7()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO teams (id, organization_id, name, archived_at) "
                "VALUES (:id, :org, :name, :archived)"
            ),
            {
                "id": team_id,
                "org": organization_id,
                "name": name,
                "archived": datetime.now(UTC) if archived else None,
            },
        )
        for member in members:
            await conn.execute(
                text(
                    "INSERT INTO team_members (organization_id, team_id, user_id) "
                    "VALUES (:org, :team, :user)"
                ),
                {"org": organization_id, "team": team_id, "user": member},
            )
    return team_id


async def limit_to_teams(engine: AsyncEngine, user_id: UUID) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET access_scope = 'teams' WHERE id = :id"), {"id": user_id}
        )


async def test_who_sees_which_work(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_user
) -> None:
    acme = await make_organization("Acme")
    everyone = await make_user(acme)
    limited = await make_user(acme)
    loner = await make_user(acme)
    someone = await make_user(acme)
    await limit_to_teams(admin_engine, limited)
    await limit_to_teams(admin_engine, loner)
    team_a = await team(admin_engine, acme, "A", [limited], archived=False)
    team_b = await team(admin_engine, acme, "B", [], archived=False)
    team_c = await team(admin_engine, acme, "C", [limited], archived=True)

    work = values(
        column("label", String), column("team_id", Uuid), column("owner_id", Uuid), name="work"
    ).data(
        [
            ("a", team_a, someone),
            ("b", team_b, someone),
            ("c", team_c, someone),
            ("limited-own", None, limited),
            ("loner-own", None, loner),
        ]
    )

    async def visible_to(user_id: UUID) -> set[str]:
        async with app_db.tenant(acme) as session:
            scope = await resource_scope(session, user_id)
            clause = scope_clause(scope, team_column=work.c.team_id, owner_column=work.c.owner_id)
            return set((await session.scalars(select(work.c.label).where(clause))).all())

    assert await visible_to(everyone) == {"a", "b", "c", "limited-own", "loner-own"}
    # An archived team no longer widens what its members see.
    assert await visible_to(limited) == {"a", "limited-own"}
    assert await visible_to(loner) == {"loner-own"}


async def test_the_scope_says_how_it_was_decided(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_user
) -> None:
    acme = await make_organization("Acme")
    everyone = await make_user(acme)
    limited = await make_user(acme)
    await limit_to_teams(admin_engine, limited)
    team_a = await team(admin_engine, acme, "A", [limited, everyone], archived=False)

    async with app_db.tenant(acme) as session:
        wide = await resource_scope(session, everyone)
        narrow = await resource_scope(session, limited)
    assert (wide.organization_wide, wide.user_id) == (True, everyone)
    assert (narrow.organization_wide, narrow.team_ids) == (False, frozenset({team_a}))
