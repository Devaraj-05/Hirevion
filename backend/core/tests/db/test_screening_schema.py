"""Screening configurations, results and application history (SP-05 Task 1)."""

from collections.abc import Awaitable, Callable
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.db.isolation import find_isolation_problems
from hirevion_core.db.session import Database
from hirevion_core.ids import uuid7
from hirevion_core.models import ApplicationHistory, ScreeningConfig, ScreeningResult

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]


async def run(engine: AsyncEngine, sql: str, **values: object) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(sql), values)


async def application(engine: AsyncEngine, org: UUID) -> tuple[UUID, UUID, UUID]:
    job, candidate, app = uuid7(), uuid7(), uuid7()
    await run(
        engine,
        "INSERT INTO jobs (id, organization_id, number, title) VALUES (:id, :org, 1, 'Engineer')",
        id=job,
        org=org,
    )
    await run(
        engine,
        "INSERT INTO candidates (id, organization_id, name) VALUES (:id, :org, 'Asha')",
        id=candidate,
        org=org,
    )
    await run(
        engine,
        "INSERT INTO applications (id, organization_id, candidate_id, job_id) "
        "VALUES (:id, :org, :candidate, :job)",
        id=app,
        org=org,
        candidate=candidate,
        job=job,
    )
    return job, candidate, app


async def test_screening_tables_are_tenant_scoped(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    acme = await make_organization("Acme")
    globex = await make_organization("Globex")
    for org in (acme, globex):
        job, candidate, app = await application(admin_engine, org)
        await run(
            admin_engine,
            "INSERT INTO screening_configs (id, organization_id, weights) VALUES (:id, :org, '{}')",
            id=uuid7(),
            org=org,
        )
        await run(
            admin_engine,
            "INSERT INTO screening_results (id, organization_id, application_id, job_id, "
            "candidate_id, cache_key, score) VALUES (:id, :org, :app, :job, :candidate, :key, 80)",
            id=uuid7(),
            org=org,
            app=app,
            job=job,
            candidate=candidate,
            key=f"key-{org}",
        )
        await run(
            admin_engine,
            "INSERT INTO application_history (id, organization_id, application_id, from_stage, "
            "to_stage, action) VALUES (:id, :org, :app, 'parsed', 'screened', 'screened')",
            id=uuid7(),
            org=org,
            app=app,
        )
    async with app_db.tenant(acme) as session:
        assert len((await session.scalars(select(ScreeningConfig.id))).all()) == 1
        assert len((await session.scalars(select(ScreeningResult.id))).all()) == 1
        assert len((await session.scalars(select(ApplicationHistory.id))).all()) == 1
    with pytest.raises(DBAPIError, match="row-level security"):
        async with app_db.tenant(acme) as session:
            session.add(ScreeningConfig(organization_id=globex, weights={}))


async def test_an_organisation_has_one_default_and_one_configuration_per_job(
    admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    acme = await make_organization("Acme")
    job, _, _ = await application(admin_engine, acme)
    insert = (
        "INSERT INTO screening_configs (id, organization_id, job_id, weights) "
        "VALUES (:id, :org, :job, '{}')"
    )
    await run(admin_engine, insert, id=uuid7(), org=acme, job=None)
    await run(admin_engine, insert, id=uuid7(), org=acme, job=job)
    with pytest.raises(IntegrityError):
        await run(admin_engine, insert, id=uuid7(), org=acme, job=None)
    with pytest.raises(IntegrityError):
        await run(admin_engine, insert, id=uuid7(), org=acme, job=job)


async def test_the_new_tables_pass_the_isolation_harness(admin_engine: AsyncEngine) -> None:
    async with admin_engine.connect() as conn:
        assert await find_isolation_problems(conn) == []
