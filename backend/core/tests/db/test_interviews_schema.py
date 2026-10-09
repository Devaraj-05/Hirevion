"""Interviews, invitations and candidate accounts (SP-07a Task 1)."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.db.isolation import find_isolation_problems
from hirevion_core.db.session import Database
from hirevion_core.ids import uuid7
from hirevion_core.models import CandidateAccount, Interview

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]
NOW = datetime.now(UTC)


async def insert_interview(
    engine: AsyncEngine,
    hiring: object,
    *,
    status: str = "invited",
    starts_at: datetime | None = None,
    expires_at: datetime | None = None,
    invited_at: datetime | None = None,
    number: int | None = None,
) -> UUID:
    interview_id = uuid7()
    async with engine.begin() as conn:
        if number is None:
            number = await conn.scalar(
                text(
                    "SELECT coalesce(max(number), 0) + 1 FROM interviews WHERE organization_id = :o"
                ),
                {"o": hiring.organization_id},  # type: ignore[attr-defined]
            )
        await conn.execute(
            text(
                "INSERT INTO interviews (id, organization_id, number, application_id, "
                "candidate_id, job_id, template_id, template_version, status, starts_at, "
                "expires_at, duration_minutes, invited_at) VALUES (:id, :org, :number, :app, "
                ":candidate, :job, :template, 1, :status, :starts, :expires, 45, :invited)"
            ),
            {
                "id": interview_id,
                "org": hiring.organization_id,  # type: ignore[attr-defined]
                "number": number,
                "app": hiring.application_id,  # type: ignore[attr-defined]
                "candidate": hiring.candidate_id,  # type: ignore[attr-defined]
                "job": hiring.job_id,  # type: ignore[attr-defined]
                "template": hiring.template_id,  # type: ignore[attr-defined]
                "status": status,
                "starts": starts_at or NOW,
                "expires": expires_at or NOW + timedelta(days=2),
                "invited": invited_at,
            },
        )
    return interview_id


async def test_the_new_tables_are_isolated(admin_engine: AsyncEngine) -> None:
    async with admin_engine.connect() as conn:
        assert await find_isolation_problems(conn) == []


async def test_interviews_are_tenant_scoped(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    acme, globex = await make_organization("Acme"), await make_organization("Globex")
    mine = await insert_interview(admin_engine, await make_hiring(acme))
    await insert_interview(admin_engine, await make_hiring(globex))
    async with app_db.tenant(acme) as session:
        ids = (await session.scalars(select(Interview.id))).all()
    assert ids == [mine]


async def test_an_application_has_one_active_interview(
    admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    hiring = await make_hiring(await make_organization("Acme"))
    await insert_interview(admin_engine, hiring, status="invited")
    with pytest.raises(IntegrityError, match="uq_interviews_active_application"):
        await insert_interview(admin_engine, hiring, status="scheduled")
    # Ended interviews don't count, so the candidate can be interviewed again.
    await insert_interview(admin_engine, hiring, status="cancelled")


async def test_the_window_must_close_after_it_opens(
    admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    hiring = await make_hiring(await make_organization("Acme"))
    with pytest.raises(IntegrityError, match="ck_interviews_window"):
        await insert_interview(admin_engine, hiring, starts_at=NOW, expires_at=NOW)


async def test_applications_take_the_interview_stages(
    admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    org = await make_organization("Acme")
    for stage in ("interview", "interviewed"):
        await make_hiring(org, stage=stage, candidate_email=f"{stage}@example.test")


async def test_candidate_accounts_are_found_by_email_without_a_tenant(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    acme, globex = await make_organization("Acme"), await make_organization("Globex")
    for org in (acme, globex):
        hiring = await make_hiring(org)
        async with admin_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO candidate_accounts (id, organization_id, candidate_id, email, "
                    "name) VALUES (:id, :org, :candidate, 'Asha.Lookup@example.test', 'Asha')"
                ),
                {"id": uuid7(), "org": org, "candidate": hiring.candidate_id},
            )
    async with app_db.unscoped() as session:
        assert (await session.scalars(select(CandidateAccount))).all() == []
        rows = (
            await session.execute(
                text("SELECT * FROM auth_candidate_by_email('asha.lookup@example.test')")
            )
        ).all()
    assert {row.organization_id for row in rows} == {acme, globex}
    assert {row.status for row in rows} == {"invited"}


async def test_the_scheduler_lists_due_interviews_in_every_organisation(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    acme, globex = await make_organization("Acme"), await make_organization("Globex")
    expired = await insert_interview(
        admin_engine,
        await make_hiring(acme),
        starts_at=NOW - timedelta(days=2),
        expires_at=NOW - timedelta(minutes=1),
    )
    reminder = await insert_interview(
        admin_engine,
        await make_hiring(globex),
        starts_at=NOW + timedelta(hours=3),
        expires_at=NOW + timedelta(days=3),
        invited_at=NOW - timedelta(days=2),
    )
    later = await insert_interview(
        admin_engine,
        await make_hiring(globex),
        starts_at=NOW + timedelta(days=5),
        expires_at=NOW + timedelta(days=6),
        invited_at=NOW - timedelta(days=1),
    )
    async with app_db.unscoped() as session:
        rows = (
            await session.execute(
                text("SELECT * FROM scheduler_due_interviews(:now, interval '24 hours', 100)"),
                {"now": NOW},
            )
        ).all()
    due = {row.interview_id for row in rows}
    assert {expired, reminder} <= due
    assert later not in due
