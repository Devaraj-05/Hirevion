"""D1 code review of candidates (SP-04b): who a resume is merged with, what the profile build
keeps, and what a scope-limited reader can learn from filters and document lists."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.access import structure
from hirevion_core.access.actor import Actor
from hirevion_core.access.scope import resource_scope
from hirevion_core.candidates import candidates, dedupe, profiles
from hirevion_core.candidates.candidates import CandidateFilters
from hirevion_core.db.session import Database
from hirevion_core.documents.resume import ResumeResult
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.jobs import jobs
from hirevion_core.jobs.jobs import JobChanges
from hirevion_core.models import Application, Candidate, Document, Job

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]


def value(text_: str | None) -> dict[str, Any] | None:
    return None if text_ is None else {"value": text_, "quote": text_, "page": 1, "section": None}


def result(name: str | None, email: str | None = None, phone: str | None = None) -> ResumeResult:
    profile: dict[str, Any] = {
        "name": value(name),
        "email": value(email),
        "phone": value(phone),
        "location": value("Pune"),
        "summary": None,
        "skills": [],
        "total_experience_years": 6,
        "positions": [],
        "education": [],
        "certifications": [],
        "projects": [],
        "achievements": [],
        "languages": [],
        "links": [],
    }
    return ResumeResult(profile, 0, "fake")


@pytest.fixture
async def acme(make_organization: MakeOrganization, make_user) -> Actor:
    organization = await make_organization("Acme")
    user = await make_user(organization, roles=["recruiter"])
    return Actor(user, organization, frozenset(permissions_for(["recruiter"])))


async def new_job(app_db: Database, actor: Actor, title: str = "Engineer", **fields: Any) -> Job:
    async with app_db.tenant(actor.organization_id) as session:
        return await jobs.create_job(session, actor, JobChanges(title=title, **fields))


async def resume(
    app_db: Database, actor: Actor, job: Job, sha256: str = "a" * 64, filename: str = "cv.pdf"
) -> Document:
    async with app_db.tenant(actor.organization_id) as session:
        document = Document(
            organization_id=actor.organization_id,
            kind="resume",
            job_id=job.id,
            filename=filename,
            sha256=sha256,
            status="parsing",
            created_by=actor.user_id,
        )
        session.add(document)
        await session.flush()
        return document


async def build(
    app_db: Database, actor: Actor, document: Document, parsed: ResumeResult
) -> Candidate:
    async with app_db.tenant(actor.organization_id) as session:
        document = await session.get_one(Document, document.id)
        return await profiles.build(session, document, parsed, flags={}, embedding=[0.1] * 1536)


async def test_a_shared_phone_with_another_email_is_a_possible_duplicate_not_a_merge(
    app_db: Database, acme: Actor
) -> None:
    job = await new_job(app_db, acme)
    agency = await build(
        app_db,
        acme,
        await resume(app_db, acme, job),
        result("Asha Rao", "asha@x.test", "+91 98765 43210"),
    )
    other = await build(
        app_db,
        acme,
        await resume(app_db, acme, job, "b" * 64),
        result("Ravi Kumar", "ravi@y.test", "+91 98765 43210"),
    )
    assert other.id != agency.id
    assert other.flags["possible_duplicate_of"] == str(agency.id)
    async with app_db.tenant(acme.organization_id) as session:
        assert (await session.get_one(Candidate, agency.id)).email == "asha@x.test"
        # The same phone and no email on the new resume still finds the person.
        same = await dedupe.match(session, email=None, phone="098765 43210", name="Asha Rao")
        assert same.candidate is not None and same.candidate.id == agency.id


async def test_a_resume_without_a_verified_name_keeps_the_candidates_name(
    app_db: Database, acme: Actor
) -> None:
    job = await new_job(app_db, acme)
    first = await build(
        app_db, acme, await resume(app_db, acme, job), result("Asha Rao", "asha@x.test")
    )
    again = await build(
        app_db,
        acme,
        await resume(app_db, acme, job, "b" * 64, filename="resume_final_v2.pdf"),
        result(None, "asha@x.test"),
    )
    assert again.id == first.id
    async with app_db.tenant(acme.organization_id) as session:
        assert (await session.get_one(Candidate, first.id)).name == "Asha Rao"


async def test_resumes_named_only_by_their_file_do_not_merge_into_one_candidate(
    app_db: Database, acme: Actor
) -> None:
    job = await new_job(app_db, acme)
    one = await build(
        app_db, acme, await resume(app_db, acme, job, filename="resume.pdf"), result(None)
    )
    two = await build(
        app_db, acme, await resume(app_db, acme, job, "b" * 64, filename="resume.pdf"), result(None)
    )
    assert one.id != two.id
    assert one.name == "resume"


async def test_filters_and_documents_never_reveal_jobs_outside_the_readers_scope(
    app_db: Database, admin_engine: AsyncEngine, acme: Actor, make_user
) -> None:
    limited = Actor(
        await make_user(acme.organization_id),
        acme.organization_id,
        frozenset(permissions_for(["recruiter"])),
    )
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET access_scope = 'teams' WHERE id = :id"), {"id": limited.user_id}
        )
    async with app_db.tenant(acme.organization_id) as session:
        team = await structure.create_team(session, acme, "Platform hiring", None, None)
        await structure.add_member(session, acme, team.id, limited.user_id)
    team_job = await new_job(app_db, acme, "Team job", team_id=team.id)
    secret_job = await new_job(app_db, acme, "Secret job")
    candidate = await build(
        app_db, acme, await resume(app_db, acme, team_job), result("Asha Rao", "asha@x.test")
    )
    await build(
        app_db,
        acme,
        await resume(app_db, acme, secret_job, "b" * 64),
        result("Asha Rao", "asha@x.test"),
    )
    async with app_db.tenant(acme.organization_id) as session:
        await session.execute(
            Application.__table__.update()
            .where(Application.job_id == secret_job.id)
            .values(stage="shortlisted")
        )

    async with app_db.tenant(acme.organization_id) as session:
        scope = await resource_scope(session, limited.user_id)

        async def found(filters: CandidateFilters) -> list[UUID]:
            rows = await session.scalars(candidates.candidates_statement(scope, filters))
            return [row.id for row in rows]

        assert await found(CandidateFilters()) == [candidate.id]
        # Neither a filter on the secret job, nor on a stage only it has, matches.
        assert await found(CandidateFilters(job_id=secret_job.id)) == []
        assert await found(CandidateFilters(stage_group="shortlisted")) == []
        assert await found(CandidateFilters(stage_group="screening")) == [candidate.id]
        detail = await candidates.get_candidate(session, candidate.id, scope)
        assert [job.title for _, job in detail.applications] == ["Team job"]
        assert [document.job_id for document in detail.documents] == [team_job.id]
