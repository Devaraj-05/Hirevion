"""SP-02b's tables and functions: departments, teams, custom-role permissions, access scope,
step-up, and the platform's organisation listing (plan Task 1)."""

import hashlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.db.session import Database, switch_tenant
from hirevion_core.ids import uuid7
from hirevion_core.models import Department, Organization, RolePermission, Team, TeamMember

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]


async def add_department(engine: AsyncEngine, organization_id: UUID, name: str) -> UUID:
    department_id = uuid7()
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO departments (id, organization_id, name) VALUES (:id, :org, :name)"),
            {"id": department_id, "org": organization_id, "name": name},
        )
    return department_id


async def add_team(
    engine: AsyncEngine, organization_id: UUID, name: str, department_id: UUID | None = None
) -> UUID:
    team_id = uuid7()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO teams (id, organization_id, name, department_id) "
                "VALUES (:id, :org, :name, :department)"
            ),
            {"id": team_id, "org": organization_id, "name": name, "department": department_id},
        )
    return team_id


async def add_member(engine: AsyncEngine, organization_id: UUID, team: UUID, user: UUID) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO team_members (organization_id, team_id, user_id) "
                "VALUES (:org, :team, :user)"
            ),
            {"org": organization_id, "team": team, "user": user},
        )


async def add_custom_role(engine: AsyncEngine, organization_id: UUID, name: str) -> UUID:
    role_id = uuid7()
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO roles (id, organization_id, name) VALUES (:id, :org, :name)"),
            {"id": role_id, "org": organization_id, "name": name},
        )
    return role_id


async def test_new_tables_are_tenant_scoped(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user,
) -> None:
    acme = await make_organization("Acme")
    globex = await make_organization("Globex")
    rows: dict[UUID, tuple[UUID, UUID, UUID]] = {}
    for org in (acme, globex):
        department = await add_department(admin_engine, org, "Engineering")
        team = await add_team(admin_engine, org, "Platform hiring", department)
        user = await make_user(org)
        await add_member(admin_engine, org, team, user)
        role = await add_custom_role(admin_engine, org, "Sourcer")
        async with admin_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO role_permissions (organization_id, role_id, permission) "
                    "VALUES (:org, :role, 'jobs.view')"
                ),
                {"org": org, "role": role},
            )
        rows[org] = (department, team, role)

    async with app_db.tenant(acme) as session:
        assert (await session.scalars(select(Department.id))).all() == [rows[acme][0]]
        assert (await session.scalars(select(Team.id))).all() == [rows[acme][1]]
        assert (await session.scalars(select(TeamMember.team_id))).all() == [rows[acme][1]]
        assert (await session.scalars(select(RolePermission.role_id))).all() == [rows[acme][2]]

    with pytest.raises(DBAPIError, match="row-level security"):
        async with app_db.tenant(acme) as session:
            session.add(Department(organization_id=globex, name="Sales"))


async def test_a_team_cannot_use_another_organisations_department(
    admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    acme = await make_organization("Acme")
    globex = await make_organization("Globex")
    globex_department = await add_department(admin_engine, globex, "Engineering")
    with pytest.raises(IntegrityError):
        await add_team(admin_engine, acme, "Platform hiring", globex_department)


async def test_a_team_cannot_have_another_organisations_member(
    admin_engine: AsyncEngine, make_organization: MakeOrganization, make_user
) -> None:
    acme = await make_organization("Acme")
    globex = await make_organization("Globex")
    team = await add_team(admin_engine, acme, "Platform hiring")
    outsider = await make_user(globex)
    with pytest.raises(IntegrityError):
        await add_member(admin_engine, acme, team, outsider)


async def test_names_are_unique_per_organisation_ignoring_case(
    admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    acme = await make_organization("Acme")
    globex = await make_organization("Globex")
    await add_department(admin_engine, acme, "Engineering")
    await add_department(admin_engine, globex, "engineering")
    await add_team(admin_engine, acme, "Platform hiring")
    with pytest.raises(IntegrityError):
        await add_department(admin_engine, acme, "engineering")
    with pytest.raises(IntegrityError):
        await add_team(admin_engine, acme, "PLATFORM HIRING")


async def test_a_custom_role_cannot_reuse_a_system_roles_name(
    admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    acme = await make_organization("Acme")
    with pytest.raises(IntegrityError):
        await add_custom_role(admin_engine, acme, "recruiter")


async def test_role_permissions_must_look_like_permissions(
    admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    acme = await make_organization("Acme")
    role = await add_custom_role(admin_engine, acme, "Sourcer")
    with pytest.raises(IntegrityError):
        async with admin_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO role_permissions (organization_id, role_id, permission) "
                    "VALUES (:org, :role, 'Not a permission')"
                ),
                {"org": acme, "role": role},
            )


async def test_the_app_creates_an_organisation_only_inside_its_own_tenant(
    app_db: Database,
) -> None:
    new_id = uuid7()
    async with app_db.tenant(new_id) as session:
        session.add(Organization(id=new_id, name="Initech", slug=f"initech-{new_id.hex[-12:]}"))

    other = uuid7()
    with pytest.raises(DBAPIError, match="row-level security"):
        async with app_db.tenant(uuid7()) as session:
            session.add(Organization(id=other, name="Hooli", slug=f"hooli-{other.hex[-12:]}"))


async def test_platform_organizations_lists_every_organisation_with_its_user_count(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user,
) -> None:
    acme = await make_organization("Acme")
    await make_user(acme)
    await make_user(acme)

    async with app_db.unscoped() as session:
        rows = {
            row.id: row
            for row in await session.execute(text("SELECT * FROM platform_organizations()"))
        }
    assert rows[acme].user_count == 2
    assert rows[acme].status == "active"
    assert rows[UUID("00000000-0000-7000-8000-000000000001")].slug == "platform"

    async with admin_engine.connect() as conn:
        grants = (
            await conn.execute(
                text(
                    "SELECT has_function_privilege('hirevion_app', 'platform_organizations()', "
                    "'EXECUTE') AS app, has_function_privilege('hirevion_relay', "
                    "'platform_organizations()', 'EXECUTE') AS relay, "
                    "pg_get_userbyid(p.proowner) AS owner, p.prosecdef AS definer "
                    "FROM pg_proc p WHERE p.proname = 'platform_organizations'"
                )
            )
        ).one()
    assert (grants.app, grants.relay, grants.owner, grants.definer) == (
        True,
        False,
        "hirevion_auth",
        True,
    )


async def test_auth_session_reports_the_step_up_time(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user,
) -> None:
    acme = await make_organization("Acme")
    user = await make_user(acme)
    token_hash = hashlib.sha256(b"a session token").digest()
    now = datetime.now(UTC)
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO web_sessions (id, organization_id, user_id, token_hash, csrf_hash, "
                "last_seen_at, expires_at, stepped_up_at) "
                "VALUES (:id, :org, :user, :token, :csrf, :now, :exp, :now)"
            ),
            {
                "id": uuid7(),
                "org": acme,
                "user": user,
                "token": token_hash,
                "csrf": hashlib.sha256(b"csrf").digest(),
                "now": now,
                "exp": now + timedelta(hours=12),
            },
        )
    async with app_db.unscoped() as session:
        row = (
            await session.execute(text("SELECT * FROM auth_session(:hash)"), {"hash": token_hash})
        ).one()
    assert row.stepped_up_at == now
    assert row.user_status == "active"


async def test_switch_tenant_moves_the_transaction_to_another_organisation(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    acme = await make_organization("Acme")
    globex = await make_organization("Globex")
    acme_department = await add_department(admin_engine, acme, "Engineering")
    globex_department = await add_department(admin_engine, globex, "Engineering")

    async with app_db.tenant(acme) as session:
        assert (await session.scalars(select(Department.id))).all() == [acme_department]
        await switch_tenant(session, globex)
        assert (await session.scalars(select(Department.id))).all() == [globex_department]
