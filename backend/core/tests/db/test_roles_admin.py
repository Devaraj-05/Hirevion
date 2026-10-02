"""Custom roles and the permission catalogue (PRD §9 "Roles, Permissions"; plan Task 8)."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.access import roles
from hirevion_core.access.actor import Actor
from hirevion_core.access.errors import Conflict, Invalid, Refused
from hirevion_core.db.session import Database
from hirevion_core.identity.grants import load_grants
from hirevion_core.identity.permissions import ASSIGNABLE_PERMISSIONS, permissions_for

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]


async def audit(engine: AsyncEngine, organization_id: UUID) -> list[tuple[str, dict[str, Any]]]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT action, details FROM audit_logs WHERE organization_id = :org ORDER BY seq"
            ),
            {"org": organization_id},
        )
        return [(row.action, row.details) for row in rows]


async def give_role(engine: AsyncEngine, organization_id: UUID, user_id: UUID, role: UUID) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO user_roles (organization_id, user_id, role_id) "
                "VALUES (:org, :user, :role)"
            ),
            {"org": organization_id, "user": user_id, "role": role},
        )


@pytest.fixture
async def acme(make_organization: MakeOrganization, make_user) -> Actor:
    organization = await make_organization("Acme")
    admin = await make_user(organization, roles=["org_admin"])
    return Actor(admin, organization, frozenset(permissions_for(["org_admin"])))


async def test_system_roles_come_first_with_their_code_permissions(
    app_db: Database, acme: Actor
) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        await roles.create_role(
            session, acme, name="Sourcer", description=None, permissions=["jobs.view"]
        )
        listed = await roles.list_roles(session)
    assert [(r.role.key, r.role.name) for r in listed] == [
        ("org_admin", "Organisation admin"),
        ("recruiter", "Recruiter"),
        ("hiring_manager", "Hiring manager"),
        ("interviewer", "Interviewer"),
        (None, "Sourcer"),
    ]
    assert listed[1].permissions == permissions_for(["recruiter"])
    assert listed[0].member_count == 1
    assert listed[-1].permissions == ["jobs.view", "account.manage"]


async def test_a_custom_role_is_created_changed_and_deleted_with_an_audit_trail(
    app_db: Database, admin_engine: AsyncEngine, acme: Actor
) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        created = await roles.create_role(
            session,
            acme,
            name=" Talent sourcer ",
            description="Finds people",
            permissions=["jobs.view", "candidates.view"],
        )
    async with app_db.tenant(acme.organization_id) as session:
        updated = await roles.update_role(
            session,
            acme,
            created.role.id,
            permissions=["jobs.view", "admin.teams.manage"],
        )
        assert "admin.teams.manage" in updated.permissions
        await roles.delete_role(session, acme, created.role.id)

    trail = await audit(admin_engine, acme.organization_id)
    assert [action for action, _ in trail] == ["role.created", "role.updated", "role.deleted"]
    assert trail[0][1]["name"] == "Talent sourcer"
    assert trail[1][1]["added"] == ["admin.teams.manage"]
    assert trail[1][1]["removed"] == ["candidates.view"]


async def test_members_feel_a_change_on_their_next_request(
    app_db: Database, admin_engine: AsyncEngine, acme: Actor, make_user
) -> None:
    asha = await make_user(acme.organization_id)
    async with app_db.tenant(acme.organization_id) as session:
        sourcer = await roles.create_role(
            session, acme, name="Sourcer", description=None, permissions=["jobs.view"]
        )
    await give_role(admin_engine, acme.organization_id, asha, sourcer.role.id)
    async with app_db.tenant(acme.organization_id) as session:
        await roles.update_role(
            session, acme, sourcer.role.id, permissions=["jobs.view", "admin.teams.manage"]
        )
        assert "admin.teams.manage" in (await load_grants(session, asha)).permissions


async def test_built_in_roles_cannot_be_changed_or_deleted(
    app_db: Database, admin_engine: AsyncEngine, acme: Actor
) -> None:
    async with admin_engine.connect() as conn:
        recruiter = await conn.scalar(
            text("SELECT id FROM roles WHERE organization_id = :org AND key = 'recruiter'"),
            {"org": acme.organization_id},
        )
    for change in (
        lambda s: roles.update_role(s, acme, recruiter, name="Talent partner"),
        lambda s: roles.delete_role(s, acme, recruiter),
    ):
        with pytest.raises(Conflict) as refusal:
            async with app_db.tenant(acme.organization_id) as session:
                await change(session)
        assert refusal.value.code == "role-system"


async def test_a_role_in_use_cannot_be_deleted(
    app_db: Database, admin_engine: AsyncEngine, acme: Actor, make_user
) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        sourcer = await roles.create_role(
            session, acme, name="Sourcer", description=None, permissions=["jobs.view"]
        )
    await give_role(
        admin_engine, acme.organization_id, await make_user(acme.organization_id), sourcer.role.id
    )
    with pytest.raises(Conflict) as refusal:
        async with app_db.tenant(acme.organization_id) as session:
            await roles.delete_role(session, acme, sourcer.role.id)
    assert refusal.value.code == "role-in-use"


async def test_names_are_unique_including_the_built_in_ones(app_db: Database, acme: Actor) -> None:
    with pytest.raises(Conflict) as refusal:
        async with app_db.tenant(acme.organization_id) as session:
            await roles.create_role(
                session, acme, name="recruiter", description=None, permissions=["jobs.view"]
            )
    assert (refusal.value.code, refusal.value.field) == ("name-taken", "name")


async def test_platform_and_unknown_permissions_are_refused(app_db: Database, acme: Actor) -> None:
    for permission in ("platform.view", "jobs.delete_everything"):
        with pytest.raises(Invalid) as refusal:
            async with app_db.tenant(acme.organization_id) as session:
                await roles.create_role(
                    session, acme, name="Odd", description=None, permissions=[permission]
                )
        assert (refusal.value.code, refusal.value.field) == ("unknown-permission", "permissions")


async def test_nobody_puts_into_a_role_what_they_do_not_hold(
    app_db: Database, acme: Actor, make_user
) -> None:
    role_manager = Actor(
        await make_user(acme.organization_id),
        acme.organization_id,
        frozenset(permissions_for([], ["admin.roles.manage", "jobs.view"])),
    )
    with pytest.raises(Refused) as refusal:
        async with app_db.tenant(acme.organization_id) as session:
            await roles.create_role(
                session,
                role_manager,
                name="Too much",
                description=None,
                permissions=["admin.users.manage"],
            )
    assert refusal.value.code == "escalation"

    # Nor do they edit a role holding more than they do.
    async with app_db.tenant(acme.organization_id) as session:
        powerful = await roles.create_role(
            session,
            acme,
            name="Powerful",
            description=None,
            permissions=["admin.users.manage", "jobs.view"],
        )
    with pytest.raises(Refused) as refusal:
        async with app_db.tenant(acme.organization_id) as session:
            await roles.update_role(
                session, role_manager, powerful.role.id, permissions=["jobs.view"]
            )
    assert refusal.value.code == "outranked"


def test_the_catalogue_lists_assignable_permissions_by_area() -> None:
    catalogue = roles.catalogue()
    assert [name for name, _ in catalogue] == list(ASSIGNABLE_PERMISSIONS)
    assert ("admin.users.manage", "admin") in catalogue
    assert ("reports.interview.view", "reports") in catalogue
