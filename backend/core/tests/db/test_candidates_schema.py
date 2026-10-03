"""Candidates, their skills and applications (SP-04b Task 1)."""

from collections.abc import Awaitable, Callable
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.db.isolation import find_isolation_problems
from hirevion_core.db.session import Database
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.ids import uuid7
from hirevion_core.models import Application, Candidate, CandidateSkill, Document

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]


async def insert(engine: AsyncEngine, sql: str, **values: object) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(sql), values)


async def add_job(engine: AsyncEngine, organization_id: UUID) -> UUID:
    job_id = uuid7()
    await insert(
        engine,
        "INSERT INTO jobs (id, organization_id, number, title) VALUES (:id, :org, 1, 'Engineer')",
        id=job_id,
        org=organization_id,
    )
    return job_id


async def add_candidate(
    engine: AsyncEngine, organization_id: UUID, email: str | None = None
) -> UUID:
    candidate_id = uuid7()
    await insert(
        engine,
        "INSERT INTO candidates (id, organization_id, name, email) "
        "VALUES (:id, :org, 'Asha', :email)",
        id=candidate_id,
        org=organization_id,
        email=email,
    )
    return candidate_id


async def test_candidate_tables_are_tenant_scoped(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    acme = await make_organization("Acme")
    globex = await make_organization("Globex")
    for org in (acme, globex):
        job = await add_job(admin_engine, org)
        candidate = await add_candidate(admin_engine, org)
        document = uuid7()
        await insert(
            admin_engine,
            "INSERT INTO documents (id, organization_id, kind, job_id, candidate_id) "
            "VALUES (:id, :org, 'resume', :job, :candidate)",
            id=document,
            org=org,
            job=job,
            candidate=candidate,
        )
        await insert(
            admin_engine,
            "INSERT INTO candidate_skills (organization_id, candidate_id, position, name) "
            "VALUES (:org, :candidate, 0, 'Python')",
            org=org,
            candidate=candidate,
        )
        await insert(
            admin_engine,
            "INSERT INTO applications (id, organization_id, candidate_id, job_id, document_id) "
            "VALUES (:id, :org, :candidate, :job, :document)",
            id=uuid7(),
            org=org,
            candidate=candidate,
            job=job,
            document=document,
        )

    async with app_db.tenant(acme) as session:
        assert len((await session.scalars(select(Candidate.id))).all()) == 1
        assert len((await session.scalars(select(CandidateSkill.candidate_id))).all()) == 1
        assert len((await session.scalars(select(Application.id))).all()) == 1
        assert len((await session.scalars(select(Document.candidate_id))).all()) == 1

    with pytest.raises(DBAPIError, match="row-level security"):
        async with app_db.tenant(acme) as session:
            session.add(Candidate(organization_id=globex, name="Not ours"))


async def test_an_application_cannot_cross_organisations(
    admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    acme = await make_organization("Acme")
    globex = await make_organization("Globex")
    acme_job = await add_job(admin_engine, acme)
    outsider = await add_candidate(admin_engine, globex)
    with pytest.raises(IntegrityError):
        await insert(
            admin_engine,
            "INSERT INTO applications (id, organization_id, candidate_id, job_id) "
            "VALUES (:id, :org, :candidate, :job)",
            id=uuid7(),
            org=acme,
            candidate=outsider,
            job=acme_job,
        )


async def test_an_email_names_one_candidate_per_organisation(
    admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    acme = await make_organization("Acme")
    globex = await make_organization("Globex")
    await add_candidate(admin_engine, acme, "asha@example.test")
    await add_candidate(admin_engine, globex, "asha@example.test")
    await add_candidate(admin_engine, acme)
    await add_candidate(admin_engine, acme)  # no email: no clash
    with pytest.raises(IntegrityError):
        await add_candidate(admin_engine, acme, "ASHA@example.test")


async def test_documents_take_archives_and_ocr(
    admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    acme = await make_organization("Acme")
    archive = uuid7()
    await insert(
        admin_engine,
        "INSERT INTO documents (id, organization_id, kind, status) "
        "VALUES (:id, :org, 'archive', 'parsed')",
        id=archive,
        org=acme,
    )
    await insert(
        admin_engine,
        "INSERT INTO documents (id, organization_id, kind, status, parent_id) "
        "VALUES (:id, :org, 'resume', 'ocr', :parent)",
        id=uuid7(),
        org=acme,
        parent=archive,
    )


def test_recruiters_manage_candidates() -> None:
    assert "candidates.manage" in permissions_for(["recruiter"])
    assert "candidates.manage" in permissions_for(["org_admin"])
    assert "candidates.manage" not in permissions_for(["hiring_manager"])


async def test_the_new_tables_pass_the_isolation_harness(admin_engine: AsyncEngine) -> None:
    async with admin_engine.connect() as conn:
        assert await find_isolation_problems(conn) == []
