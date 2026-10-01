"""What a user's roles grant: system roles from code, custom roles from `role_permissions`
(plan Task 2)."""

from collections.abc import Awaitable, Callable
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.db.session import Database
from hirevion_core.identity.grants import load_grants
from hirevion_core.identity.permissions import SYSTEM_ROLES
from hirevion_core.ids import uuid7

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]


async def give_custom_role(
    engine: AsyncEngine, organization_id: UUID, user_id: UUID, name: str, permissions: list[str]
) -> None:
    role_id = uuid7()
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO roles (id, organization_id, name) VALUES (:id, :org, :name)"),
            {"id": role_id, "org": organization_id, "name": name},
        )
        for permission in permissions:
            await conn.execute(
                text(
                    "INSERT INTO role_permissions (organization_id, role_id, permission) "
                    "VALUES (:org, :role, :permission)"
                ),
                {"org": organization_id, "role": role_id, "permission": permission},
            )
        await conn.execute(
            text(
                "INSERT INTO user_roles (organization_id, user_id, role_id) "
                "VALUES (:org, :user, :role)"
            ),
            {"org": organization_id, "user": user_id, "role": role_id},
        )


async def test_grants_combine_system_and_custom_roles(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_user
) -> None:
    acme = await make_organization("Acme")
    asha = await make_user(acme, roles=["recruiter"])
    await give_custom_role(admin_engine, acme, asha, "Sourcer", ["admin.teams.manage"])

    async with app_db.tenant(acme) as session:
        grants = await load_grants(session, asha)

    assert grants.role_keys == ["recruiter"]
    assert grants.custom_roles == ["Sourcer"]
    assert set(grants.permissions) == {*SYSTEM_ROLES["recruiter"], "admin.teams.manage"}


async def test_a_custom_role_alone_still_manages_its_own_account(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_user
) -> None:
    acme = await make_organization("Acme")
    ravi = await make_user(acme)
    await give_custom_role(admin_engine, acme, ravi, "Viewer", ["jobs.view"])

    async with app_db.tenant(acme) as session:
        grants = await load_grants(session, ravi)

    assert grants.role_keys == []
    assert grants.permissions == ["jobs.view", "account.manage"]


async def test_a_user_without_roles_has_only_the_baseline(
    app_db: Database, make_organization: MakeOrganization, make_user
) -> None:
    acme = await make_organization("Acme")
    nobody = await make_user(acme)
    async with app_db.tenant(acme) as session:
        grants = await load_grants(session, nobody)
    assert (grants.role_keys, grants.custom_roles, grants.permissions) == (
        [],
        [],
        ["account.manage"],
    )
