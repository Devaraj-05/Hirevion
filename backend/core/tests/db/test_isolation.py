"""The tenant-isolation harness and the behaviour it protects (master plan SP-01 exit criterion)."""

from collections.abc import Awaitable, Callable
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.db.isolation import find_isolation_problems
from hirevion_core.db.session import Database, create_database
from hirevion_core.models import Organization
from hirevion_core.settings import APP_ROLE, CoreSettings

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]


async def test_baseline_has_no_isolation_problems(admin_engine: AsyncEngine) -> None:
    async with admin_engine.connect() as conn:
        assert await find_isolation_problems(conn) == []


async def test_harness_reports_a_tenant_table_without_rls(admin_engine: AsyncEngine) -> None:
    async with admin_engine.begin() as conn:
        await conn.execute(text("CREATE TABLE leaky (id uuid, organization_id uuid)"))
        try:
            problems = await find_isolation_problems(conn)
        finally:
            await conn.execute(text("DROP TABLE leaky"))
    assert any("leaky" in problem and "row-level security" in problem for problem in problems)


async def test_application_role_cannot_bypass_rls(admin_engine: AsyncEngine) -> None:
    async with admin_engine.connect() as conn:
        role = (
            await conn.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = :role"),
                {"role": APP_ROLE},
            )
        ).one()
    assert tuple(role) == (False, False)


async def test_an_organisation_sees_only_itself(
    app_db: Database, make_organization: MakeOrganization
) -> None:
    acme = await make_organization("Acme")
    globex = await make_organization("Globex")

    async with app_db.tenant(acme) as session:
        assert (await session.scalars(select(Organization.id))).all() == [acme]

    async with app_db.tenant(globex) as session:
        assert (await session.scalars(select(Organization.id))).all() == [globex]

    async with app_db.unscoped() as session:
        assert (await session.scalars(select(Organization.id))).all() == []


async def test_tenant_setting_never_leaks_through_the_pool(
    core_settings: CoreSettings, migrated_database: str, make_organization: MakeOrganization
) -> None:
    acme = await make_organization("Pooled")
    db = create_database(core_settings, "app", migrated_database, pool_size=1, max_overflow=0)
    try:
        async with db.tenant(acme) as session:
            assert (await session.scalars(select(Organization.id))).all() == [acme]
        async with db.unscoped() as session:
            assert (await session.scalars(select(Organization.id))).all() == []
    finally:
        await db.dispose()


async def test_the_app_role_cannot_create_organisations(app_db: Database) -> None:
    with pytest.raises(DBAPIError, match="permission denied"):
        async with app_db.unscoped() as session:
            await session.execute(
                text(
                    "INSERT INTO organizations (id, name, slug) "
                    "VALUES (gen_random_uuid(), 'x', 'x')"
                )
            )


async def test_application_role_logs_in_with_its_scram_password(app_db: Database) -> None:
    async with app_db.unscoped() as session:
        assert (await session.execute(text("SELECT current_user"))).scalar() == APP_ROLE
