"""The organisation profile, departments and teams (PRD §9; plan Task 6)."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.access import structure
from hirevion_core.access.actor import Actor
from hirevion_core.access.errors import Conflict, Invalid, NotFound, Refused
from hirevion_core.access.organization import ProfileChanges, get_profile, update_profile
from hirevion_core.db.session import Database
from hirevion_core.identity import PLATFORM_ORGANIZATION_ID
from hirevion_core.identity.permissions import permissions_for

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]


def admin_of(organization_id: UUID, user_id: UUID) -> Actor:
    return Actor(user_id, organization_id, frozenset(permissions_for(["org_admin"])))


async def audit(engine: AsyncEngine, organization_id: UUID) -> list[tuple[str, dict[str, Any]]]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT action, details FROM audit_logs WHERE organization_id = :org ORDER BY seq"
            ),
            {"org": organization_id},
        )
        return [(row.action, row.details) for row in rows]


@pytest.fixture
async def acme(make_organization: MakeOrganization, make_user) -> Actor:
    organization = await make_organization("Acme")
    return admin_of(organization, await make_user(organization, roles=["org_admin"]))


# The organisation profile


async def test_updating_the_profile_records_which_fields_changed(
    app_db: Database, admin_engine: AsyncEngine, acme: Actor
) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        before = await get_profile(session, acme)
        assert (before.country, before.timezone, before.default_locale) == (
            "IN",
            "Asia/Kolkata",
            "en-IN",
        )
        after = await update_profile(
            session,
            acme,
            ProfileChanges(name="  Acme Talent  ", website="https://acme.example", country="US"),
        )
    assert (after.name, after.website, after.country) == (
        "Acme Talent",
        "https://acme.example",
        "US",
    )
    assert (await audit(admin_engine, acme.organization_id))[-1] == (
        "organization.profile.updated",
        {"fields": ["country", "name", "website"]},
    )


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        (ProfileChanges(timezone="Mars/Olympus_Mons"), "timezone"),
        (ProfileChanges(country="india"), "country"),
        (ProfileChanges(default_locale="fr-FR"), "default_locale"),
        (ProfileChanges(name="   "), "name"),
        (ProfileChanges(website="javascript:alert(1)"), "website"),
    ],
)
async def test_profile_values_are_checked(
    app_db: Database, acme: Actor, changes: ProfileChanges, field: str
) -> None:
    with pytest.raises(Invalid) as refusal:
        async with app_db.tenant(acme.organization_id) as session:
            await update_profile(session, acme, changes)
    assert refusal.value.field == field


async def test_the_platform_organisation_has_no_profile(app_db: Database, make_user) -> None:
    platform_admin = Actor(
        await make_user(PLATFORM_ORGANIZATION_ID, roles=["super_admin"]),
        PLATFORM_ORGANIZATION_ID,
        frozenset(permissions_for(["super_admin"])),
    )
    with pytest.raises(Refused) as refusal:
        async with app_db.tenant(PLATFORM_ORGANIZATION_ID) as session:
            await get_profile(session, platform_admin)
    assert refusal.value.code == "platform-organization"


# Departments


async def test_departments_are_created_renamed_archived_and_restored(
    app_db: Database, admin_engine: AsyncEngine, acme: Actor
) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        engineering = await structure.create_department(session, acme, " Engineering ", None)
        await structure.create_department(session, acme, "Sales", "Field sales")
    async with app_db.tenant(acme.organization_id) as session:
        await structure.update_department(session, acme, engineering.id, name="Engineering & IT")
        await structure.update_department(session, acme, engineering.id, archived=True)
        assert [d.name for d in await structure.list_departments(session)] == ["Sales"]
        listed = await structure.list_departments(session, include_archived=True)
        assert [d.name for d in listed] == ["Engineering & IT", "Sales"]
        await structure.update_department(session, acme, engineering.id, archived=False)

    actions = [action for action, _ in await audit(admin_engine, acme.organization_id)]
    assert actions == [
        "department.created",
        "department.created",
        "department.updated",
        "department.archived",
        "department.restored",
    ]


async def test_department_names_are_unique_ignoring_case(app_db: Database, acme: Actor) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        await structure.create_department(session, acme, "Engineering", None)
    with pytest.raises(Conflict) as refusal:
        async with app_db.tenant(acme.organization_id) as session:
            await structure.create_department(session, acme, "ENGINEERING", None)
    assert (refusal.value.code, refusal.value.field) == ("name-taken", "name")


async def test_an_unknown_department_is_not_found(app_db: Database, acme: Actor) -> None:
    with pytest.raises(NotFound):
        async with app_db.tenant(acme.organization_id) as session:
            await structure.update_department(session, acme, acme.user_id, name="Nope")


# Teams


async def test_teams_list_their_department_and_member_count(
    app_db: Database, acme: Actor, make_user
) -> None:
    member = await make_user(acme.organization_id)
    async with app_db.tenant(acme.organization_id) as session:
        engineering = await structure.create_department(session, acme, "Engineering", None)
        hiring = await structure.create_team(
            session, acme, "Platform hiring", "Backend roles", engineering.id
        )
        await structure.create_team(session, acme, "Campus", None, None)
        await structure.add_member(session, acme, hiring.id, member)
        await structure.add_member(session, acme, hiring.id, member)  # already there: no-op
        teams = await structure.list_teams(session)
    assert [(t.team.name, t.department_name, t.member_count) for t in teams] == [
        ("Campus", None, 0),
        ("Platform hiring", "Engineering", 1),
    ]


async def test_a_team_needs_a_live_department(app_db: Database, acme: Actor) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        old = await structure.create_department(session, acme, "Old", None)
        await structure.update_department(session, acme, old.id, archived=True)
    with pytest.raises(Invalid) as refusal:
        async with app_db.tenant(acme.organization_id) as session:
            await structure.create_team(session, acme, "Legacy", None, old.id)
    assert refusal.value.field == "department_id"


async def test_members_come_and_go_and_are_audited(
    app_db: Database, admin_engine: AsyncEngine, acme: Actor, make_user
) -> None:
    member = await make_user(acme.organization_id, name="Asha Rao")
    async with app_db.tenant(acme.organization_id) as session:
        team = await structure.create_team(session, acme, "Platform hiring", None, None)
        await structure.add_member(session, acme, team.id, member)
        assert [u.name for u in await structure.list_members(session, team.id)] == ["Asha Rao"]
        await structure.remove_member(session, acme, team.id, member)
        assert await structure.list_members(session, team.id) == []
    actions = [action for action, _ in await audit(admin_engine, acme.organization_id)]
    assert actions[-2:] == ["team.member.added", "team.member.removed"]


async def test_an_archived_team_takes_no_new_members(
    app_db: Database, acme: Actor, make_user
) -> None:
    member = await make_user(acme.organization_id)
    async with app_db.tenant(acme.organization_id) as session:
        team = await structure.create_team(session, acme, "Old team", None, None)
        await structure.update_team(session, acme, team.id, archived=True)
    with pytest.raises(Conflict) as refusal:
        async with app_db.tenant(acme.organization_id) as session:
            await structure.add_member(session, acme, team.id, member)
    assert refusal.value.code == "team-archived"


async def test_another_organisations_user_cannot_join(
    app_db: Database, acme: Actor, make_organization: MakeOrganization, make_user
) -> None:
    globex = await make_organization("Globex")
    outsider = await make_user(globex)
    with pytest.raises(NotFound):
        async with app_db.tenant(acme.organization_id) as session:
            team = await structure.create_team(session, acme, "Platform hiring", None, None)
            await structure.add_member(session, acme, team.id, outsider)
