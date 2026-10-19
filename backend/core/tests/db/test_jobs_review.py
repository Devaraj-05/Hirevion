"""D1 code review of jobs and skills (SP-04a): concurrent edits, references that were archived
since, the open-job rules, number ranges, hiring-manager access and the skills taxonomy."""

import asyncio
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.access import structure
from hirevion_core.access.actor import Actor
from hirevion_core.access.errors import Invalid
from hirevion_core.access.scope import resource_scope
from hirevion_core.db.session import Database
from hirevion_core.documents import intake
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.jobs import jobs, taxonomy
from hirevion_core.jobs.jobs import JobChanges, JobFilters, SkillInput
from hirevion_core.models import Document, Job

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]


def recruiter_actor(organization_id: UUID, user_id: UUID) -> Actor:
    return Actor(user_id, organization_id, frozenset(permissions_for(["recruiter"])))


@pytest.fixture
async def acme(make_organization: MakeOrganization, make_user) -> Actor:
    organization = await make_organization("Acme")
    return recruiter_actor(organization, await make_user(organization, roles=["recruiter"]))


async def open_job(app_db: Database, actor: Actor, **fields: Any) -> UUID:
    async with app_db.tenant(actor.organization_id) as session:
        job = await jobs.create_job(
            session,
            actor,
            JobChanges(
                title="Engineer",
                description="Build APIs.",
                skills=[SkillInput("Python")],
                **fields,
            ),
        )
        await jobs.set_status(session, actor, job.id, "open")
        return job.id


async def test_two_edits_at_once_both_land_as_versions(app_db: Database, acme: Actor) -> None:
    job_id = await open_job(app_db, acme)

    async def edit(**fields: Any) -> None:
        async with app_db.tenant(acme.organization_id) as session:
            await jobs.update_job(session, acme, job_id, JobChanges(**fields))
            await asyncio.sleep(0.2)  # hold the transaction open while the other edit starts

    await asyncio.gather(edit(location="Pune"), edit(domain=["Fintech"]))
    async with app_db.tenant(acme.organization_id) as session:
        versions = await jobs.list_versions(session, job_id)
        job = await jobs.get_job(session, job_id, await resource_scope(session, acme.user_id))
    assert [v.version for v in versions] == [1, 2, 3, 4]
    assert (job.job.location, job.job.domain) == ("Pune", ["Fintech"])


async def test_a_job_keeps_the_recruiter_and_department_that_were_archived_since(
    app_db: Database, admin_engine: AsyncEngine, acme: Actor, make_user
) -> None:
    colleague = await make_user(acme.organization_id, roles=["recruiter"])
    async with app_db.tenant(acme.organization_id) as session:
        department = await structure.create_department(session, acme, "Platform", None)
        job = await jobs.create_job(
            session,
            acme,
            JobChanges(title="Engineer", recruiter_id=colleague, department_id=department.id),
        )
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET status = 'disabled' WHERE id = :id"), {"id": colleague}
        )
        await conn.execute(
            text("UPDATE departments SET archived_at = now() WHERE id = :id"), {"id": department.id}
        )
    # The form sends the whole job back: the unchanged references must not stop the edit.
    async with app_db.tenant(acme.organization_id) as session:
        saved = await jobs.update_job(
            session,
            acme,
            job.id,
            JobChanges(recruiter_id=colleague, department_id=department.id, location="Pune"),
        )
        assert saved.location == "Pune"
        # A new choice must still be current.
        with pytest.raises(Invalid):
            await jobs.update_job(session, acme, job.id, JobChanges(recruiter_id=UUID(int=5)))


async def test_an_open_job_cannot_be_edited_into_one_that_could_not_be_opened(
    app_db: Database, acme: Actor
) -> None:
    job_id = await open_job(app_db, acme)
    async with app_db.tenant(acme.organization_id) as session:
        for changes in (
            JobChanges(description="  "),
            JobChanges(skills=[SkillInput("Go", "preferred")]),
            JobChanges(skills=[]),
        ):
            with pytest.raises(Invalid) as refusal:
                async with session.begin_nested():
                    await jobs.update_job(session, acme, job_id, changes)
            assert refusal.value.code == "job-incomplete"
        await jobs.set_status(session, acme, job_id, "paused")
        await jobs.update_job(session, acme, job_id, JobChanges(description=""))  # paused: fine


@pytest.mark.parametrize(
    "changes",
    [
        JobChanges(salary_max=Decimal("1e15")),
        JobChanges(salary_min=Decimal("Infinity")),
        JobChanges(experience_min=Decimal("NaN")),
    ],
)
async def test_numbers_outside_what_the_columns_hold_are_refused_not_a_server_error(
    app_db: Database, acme: Actor, changes: JobChanges
) -> None:
    job_id = await open_job(app_db, acme)
    async with app_db.tenant(acme.organization_id) as session:
        with pytest.raises(Invalid):
            await jobs.update_job(session, acme, job_id, changes)


async def test_saving_the_same_years_again_is_not_a_change(app_db: Database, acme: Actor) -> None:
    job_id = await open_job(app_db, acme)
    changes = JobChanges(
        experience_min=Decimal("2.25"),
        salary_min=Decimal("100.005"),
        skills=[SkillInput("Python", "required", Decimal("1.25"))],
    )
    async with app_db.tenant(acme.organization_id) as session:
        await jobs.update_job(session, acme, job_id, changes)
    async with app_db.tenant(acme.organization_id) as session:
        job = await jobs.update_job(session, acme, job_id, changes)
    assert job.experience_min == Decimal("2.3")  # as the database rounds it
    assert job.version == 3  # created, opened, edited once


async def test_too_long_an_item_is_not_reported_as_too_many(app_db: Database, acme: Actor) -> None:
    job_id = await open_job(app_db, acme)
    async with app_db.tenant(acme.organization_id) as session:
        with pytest.raises(Invalid) as refusal:
            await jobs.update_job(session, acme, job_id, JobChanges(responsibilities=["x" * 600]))
    assert refusal.value.code == "too-long"


async def test_a_failed_skills_check_leaves_the_job_untouched(
    app_db: Database, acme: Actor
) -> None:
    job_id = await open_job(app_db, acme)
    async with app_db.tenant(acme.organization_id) as session:
        job = await session.get_one(Job, job_id)
        with pytest.raises(Invalid):
            await jobs.update_job(
                session,
                acme,
                job_id,
                JobChanges(title="Renamed", skills=[SkillInput("Go", "nonsense")]),
            )
        assert job.title == "Engineer"


async def test_the_description_of_a_long_job_description_fits_the_job(
    app_db: Database, acme: Actor
) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        job = await jobs.create_job(session, acme, JobChanges(title="Engineer"))
        document = await intake.submit_jd_text(session, acme, job.id, "word " * 15_000)
        (await session.get_one(Document, document.id)).status = "parsed"
        (await session.get_one(Document, document.id)).text = "word " * 15_000
        applied = await jobs.apply_jd(session, acme, job.id, document.id, JobChanges())
        assert 0 < len(applied.description) <= jobs.DESCRIPTION_MAX
        version = (await jobs.list_versions(session, job.id))[-1]
        assert version.snapshot["jd_document_id"] == str(document.id)


async def test_creating_and_editing_a_job_asks_for_its_embedding(
    app_db: Database, admin_engine: AsyncEngine, acme: Actor, empty_outbox: None
) -> None:
    job_id = await open_job(app_db, acme)
    async with app_db.tenant(acme.organization_id) as session:
        await jobs.update_job(session, acme, job_id, JobChanges(location="Pune"))  # not text
        await jobs.update_job(session, acme, job_id, JobChanges(title="Staff Engineer"))
    async with admin_engine.connect() as conn:
        payloads = (
            await conn.execute(
                text("SELECT payload FROM outbox_events WHERE organization_id = :org"),
                {"org": acme.organization_id},
            )
        ).scalars()
        asked = [p for p in payloads if p == {"action": "embed-job", "job_id": str(job_id)}]
    assert len(asked) == 2  # on creating it, and on renaming it


async def test_a_hiring_manager_reaches_the_jobs_assigned_to_them_whatever_their_scope(
    app_db: Database, admin_engine: AsyncEngine, acme: Actor, make_user
) -> None:
    manager = await make_user(acme.organization_id, roles=["hiring_manager"])
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET access_scope = 'teams' WHERE id = :id"), {"id": manager}
        )
    async with app_db.tenant(acme.organization_id) as session:
        mine = await jobs.create_job(
            session, acme, JobChanges(title="Mine", hiring_manager_id=manager)
        )
        await jobs.create_job(session, acme, JobChanges(title="Not mine"))
        scope = await resource_scope(session, manager)
        listed = (await session.scalars(jobs.jobs_statement(scope, JobFilters()))).all()
        assert [job.id for job in listed] == [mine.id]
        assert (await jobs.get_job(session, mine.id, scope)).job.title == "Mine"


async def test_dot_net_is_a_skill_and_wildcards_are_not_searched(
    app_db: Database, acme: Actor
) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        resolved = await taxonomy.resolve_skills(
            session, [".NET", ".NET Core", "(React),", "node.js."]
        )
        assert [skill.name if skill else None for skill in resolved] == [
            ".NET",
            ".NET",
            "React",
            "Node.js",
        ]
        assert await taxonomy.search_skills(session, "_") == []
        assert await taxonomy.search_skills(session, "%") == []
