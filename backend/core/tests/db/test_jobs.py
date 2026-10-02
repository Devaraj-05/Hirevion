"""Jobs: create, edit, lifecycle, versions and scoped listing (SP-04a Task 3)."""

from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.access import structure
from hirevion_core.access.actor import Actor
from hirevion_core.access.errors import Conflict, Invalid, NotFound
from hirevion_core.access.scope import resource_scope
from hirevion_core.db.session import Database
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.jobs import jobs
from hirevion_core.jobs.jobs import JobChanges, JobFilters, SkillInput

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]


def recruiter_actor(organization_id: UUID, user_id: UUID) -> Actor:
    return Actor(user_id, organization_id, frozenset(permissions_for(["recruiter"])))


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
    return recruiter_actor(organization, await make_user(organization, roles=["recruiter"]))


FULL = JobChanges(
    title="Senior Python Engineer",
    description="We build hiring software.",
    location="Bengaluru",
    work_model="hybrid",
    experience_min=Decimal(4),
    experience_max=Decimal(8),
    responsibilities=["Design APIs", "  Review code  "],
    skills=[SkillInput("py"), SkillInput("JS", "preferred"), SkillInput("python")],
)


async def test_creating_numbers_versions_and_audits(
    app_db: Database, admin_engine: AsyncEngine, acme: Actor
) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        first = await jobs.create_job(session, acme, FULL)
        second = await jobs.create_job(session, acme, JobChanges(title="Data Analyst"))
        detail = await jobs.get_job(session, first.id, await resource_scope(session, acme.user_id))
        versions = await jobs.list_versions(session, first.id)

    assert (first.number, second.number) == (1, 2)
    assert (first.status, first.version, first.recruiter_id) == ("draft", 1, acme.user_id)
    assert first.responsibilities == ["Design APIs", "Review code"]
    assert [(s.name, s.importance, s.skill_id is not None) for s in detail.skills] == [
        ("Python", "required", True),
        ("JavaScript", "preferred", True),
    ]
    assert [(v.version, v.reason) for v in versions] == [(1, "created")]
    assert versions[0].snapshot["title"] == "Senior Python Engineer"
    assert (await audit(admin_engine, acme.organization_id))[0] == (
        "job.created",
        {"number": 1, "title": "Senior Python Engineer"},
    )


async def test_editing_writes_a_new_version_with_the_changed_fields(
    app_db: Database, admin_engine: AsyncEngine, acme: Actor
) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        job = await jobs.create_job(session, acme, FULL)
    async with app_db.tenant(acme.organization_id) as session:
        job = await jobs.update_job(
            session,
            acme,
            job.id,
            JobChanges(title="Staff Python Engineer", skills=[SkillInput("Go")]),
        )
        versions = await jobs.list_versions(session, job.id)
    assert (job.version, job.title) == (2, "Staff Python Engineer")
    assert [v.reason for v in versions] == ["created", "edited"]
    assert [s["name"] for s in versions[1].snapshot["skills"]] == ["Go"]
    action, details = (await audit(admin_engine, acme.organization_id))[-1]
    assert (action, details) == ("job.updated", {"fields": ["skills", "title"]})


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        (JobChanges(title="  "), "title"),
        (JobChanges(experience_min=Decimal(9), experience_max=Decimal(3)), "experience_max"),
        (JobChanges(salary_min=Decimal(10), salary_max=Decimal(5)), "salary_max"),
        (JobChanges(salary_currency="rupees"), "salary_currency"),
        (JobChanges(work_model="moon"), "work_model"),
        (JobChanges(employment_type="forever"), "employment_type"),
        (JobChanges(skills=[SkillInput("Python", "essential")]), "skills"),
    ],
)
async def test_fields_are_checked(
    app_db: Database, acme: Actor, changes: JobChanges, field: str
) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        job = await jobs.create_job(session, acme, JobChanges(title="Engineer"))
    with pytest.raises(Invalid) as refusal:
        async with app_db.tenant(acme.organization_id) as session:
            await jobs.update_job(session, acme, job.id, changes)
    assert refusal.value.field == field


async def test_assignment_stays_in_the_organisation_and_its_live_structure(
    app_db: Database, acme: Actor, make_organization: MakeOrganization, make_user
) -> None:
    outsider = await make_user(await make_organization("Globex"))
    leaver = await make_user(acme.organization_id, status="disabled")
    async with app_db.tenant(acme.organization_id) as session:
        old = await structure.create_department(session, acme, "Old", None)
        await structure.update_department(session, acme, old.id, archived=True)
    for changes, field in (
        (JobChanges(title="X", recruiter_id=outsider), "recruiter_id"),
        (JobChanges(title="X", hiring_manager_id=leaver), "hiring_manager_id"),
        (JobChanges(title="X", department_id=old.id), "department_id"),
    ):
        with pytest.raises(Invalid) as refusal:
            async with app_db.tenant(acme.organization_id) as session:
                await jobs.create_job(session, acme, changes)
        assert refusal.value.field == field


async def test_the_lifecycle(app_db: Database, admin_engine: AsyncEngine, acme: Actor) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        bare = await jobs.create_job(session, acme, JobChanges(title="Bare"))
        job = await jobs.create_job(session, acme, FULL)
    with pytest.raises(Invalid) as incomplete:
        async with app_db.tenant(acme.organization_id) as session:
            await jobs.set_status(session, acme, bare.id, "open")
    assert incomplete.value.code == "job-incomplete"

    async with app_db.tenant(acme.organization_id) as session:
        for status in ("open", "paused", "open", "closed", "archived"):
            job = await jobs.set_status(session, acme, job.id, status)
    assert (job.status, job.version) == ("archived", 6)
    assert (await audit(admin_engine, acme.organization_id))[-1] == (
        "job.status_changed",
        {"from": "closed", "to": "archived"},
    )
    for current, target in (("archived", "open"),):
        with pytest.raises(Conflict) as refusal:
            async with app_db.tenant(acme.organization_id) as session:
                await jobs.set_status(session, acme, job.id, target)
        assert (refusal.value.code, current) == ("invalid-transition", "archived")
    with pytest.raises(Conflict):
        async with app_db.tenant(acme.organization_id) as session:
            await jobs.set_status(session, acme, bare.id, "closed")


async def test_a_team_limited_user_sees_their_teams_jobs_and_their_own(
    app_db: Database, admin_engine: AsyncEngine, acme: Actor, make_user
) -> None:
    limited = recruiter_actor(acme.organization_id, await make_user(acme.organization_id))
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET access_scope = 'teams' WHERE id = :id"), {"id": limited.user_id}
        )
    async with app_db.tenant(acme.organization_id) as session:
        team = await structure.create_team(session, acme, "Platform hiring", None, None)
        await structure.add_member(session, acme, team.id, limited.user_id)
        team_job = await jobs.create_job(
            session, acme, JobChanges(title="Team job", team_id=team.id)
        )
        other_job = await jobs.create_job(session, acme, JobChanges(title="Someone else's"))
        own_job = await jobs.create_job(session, limited, JobChanges(title="Mine"))

    async with app_db.tenant(acme.organization_id) as session:
        scope = await resource_scope(session, limited.user_id)
        visible = (await session.scalars(jobs.jobs_statement(scope, JobFilters()))).all()
        assert {job.id for job in visible} == {team_job.id, own_job.id}
        with pytest.raises(NotFound):
            await jobs.get_job(session, other_job.id, scope)
        wide = await resource_scope(session, acme.user_id)
        searched = (
            await session.scalars(jobs.jobs_statement(wide, JobFilters(query="team")))
        ).all()
        assert [job.id for job in searched] == [team_job.id]
