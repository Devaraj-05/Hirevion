"""Jobs, skills, versions and documents (SP-04a Task 1)."""

from collections.abc import Awaitable, Callable
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.db.isolation import find_isolation_problems
from hirevion_core.db.session import Database
from hirevion_core.ids import uuid7
from hirevion_core.models import Document, Job, JobSkill, JobVersion, Skill, SkillAlias

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]


async def add_job(
    engine: AsyncEngine, organization_id: UUID, number: int, **columns: object
) -> UUID:
    job_id = uuid7()
    names = ", ".join(["id", "organization_id", "number", "title", *columns])
    values = ", ".join([":id", ":org", ":number", ":title", *(f":{name}" for name in columns)])
    async with engine.begin() as conn:
        await conn.execute(
            text(f"INSERT INTO jobs ({names}) VALUES ({values})"),  # noqa: S608 (test columns)
            {
                "id": job_id,
                "org": organization_id,
                "number": number,
                "title": "Engineer",
                **columns,
            },
        )
    return job_id


async def test_job_tables_are_tenant_scoped(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    acme = await make_organization("Acme")
    globex = await make_organization("Globex")
    acme_job = await add_job(admin_engine, acme, 1)
    globex_job = await add_job(admin_engine, globex, 1)
    async with admin_engine.begin() as conn:
        for org, job in ((acme, acme_job), (globex, globex_job)):
            await conn.execute(
                text(
                    "INSERT INTO job_skills (organization_id, job_id, position, name, importance) "
                    "VALUES (:org, :job, 0, 'Python', 'required')"
                ),
                {"org": org, "job": job},
            )
            await conn.execute(
                text(
                    "INSERT INTO job_versions (organization_id, job_id, version, snapshot, reason)"
                    " VALUES (:org, :job, 1, '{}', 'created')"
                ),
                {"org": org, "job": job},
            )
            await conn.execute(
                text(
                    "INSERT INTO documents (id, organization_id, kind, job_id) "
                    "VALUES (:id, :org, 'jd', :job)"
                ),
                {"id": uuid7(), "org": org, "job": job},
            )

    async with app_db.tenant(acme) as session:
        assert (await session.scalars(select(Job.id))).all() == [acme_job]
        assert (await session.scalars(select(JobSkill.job_id))).all() == [acme_job]
        assert (await session.scalars(select(JobVersion.job_id))).all() == [acme_job]
        assert (await session.scalars(select(Document.job_id))).all() == [acme_job]

    with pytest.raises(DBAPIError, match="row-level security"):
        async with app_db.tenant(acme) as session:
            session.add(Job(organization_id=globex, number=2, title="Not ours"))


async def test_a_job_cannot_point_into_another_organisation(
    admin_engine: AsyncEngine, make_organization: MakeOrganization, make_user
) -> None:
    acme = await make_organization("Acme")
    globex = await make_organization("Globex")
    outsider = await make_user(globex)
    with pytest.raises(IntegrityError):
        await add_job(admin_engine, acme, 1, recruiter_id=outsider)


async def test_job_numbers_are_unique_per_organisation(
    admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    acme = await make_organization("Acme")
    globex = await make_organization("Globex")
    await add_job(admin_engine, acme, 1)
    await add_job(admin_engine, globex, 1)
    with pytest.raises(IntegrityError):
        await add_job(admin_engine, acme, 1)


async def test_the_shared_taxonomy_is_seeded_and_read_only(app_db: Database) -> None:
    async with app_db.unscoped() as session:
        python = await session.scalar(select(Skill).where(Skill.name == "python"))
        assert python is not None and python.name == "Python"
        alias = await session.scalar(select(SkillAlias.skill_id).where(SkillAlias.alias == "PY"))
        assert alias == python.id
    with pytest.raises(DBAPIError, match="permission denied"):
        async with app_db.unscoped() as session:
            session.add(Skill(name="Underwater basket weaving", category="other"))


async def test_the_new_tables_pass_the_isolation_harness(admin_engine: AsyncEngine) -> None:
    async with admin_engine.connect() as conn:
        assert await find_isolation_problems(conn) == []
