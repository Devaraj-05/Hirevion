"""Candidates: de-duplication, the profile build, applications and scope (SP-04b Task 6)."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.access import structure
from hirevion_core.access.actor import Actor
from hirevion_core.access.errors import NotFound
from hirevion_core.access.scope import resource_scope
from hirevion_core.candidates import candidates, dedupe, profiles
from hirevion_core.candidates.candidates import CandidateFilters
from hirevion_core.db.session import Database
from hirevion_core.documents.resume import ResumeResult
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.jobs import jobs
from hirevion_core.jobs.jobs import JobChanges
from hirevion_core.models import Application, Candidate, CandidateSkill, Document, Job

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]


def value(text_: str | None) -> dict[str, Any] | None:
    return None if text_ is None else {"value": text_, "quote": text_, "page": 1, "section": None}


def result(
    name: str,
    email: str | None = None,
    phone: str | None = None,
    skills: tuple[str, ...] = ("py", "Kubernetes"),
) -> ResumeResult:
    profile = {
        "name": value(name),
        "email": value(email),
        "phone": value(phone),
        "location": value("Pune"),
        "summary": None,
        "skills": [
            {"name": skill, "years": 4, "quote": skill, "page": 1, "section": "skills"}
            for skill in skills
        ],
        "total_experience_years": 6,
        "positions": [
            {
                "company": "Acme Software",
                "title": "Senior Engineer",
                "start": "2020",
                "end": None,
                "current": True,
                "quote": "Senior Engineer",
                "page": 1,
                "section": "experience",
            }
        ],
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


async def resume(app_db: Database, actor: Actor, job: Job, sha256: str = "a" * 64) -> Document:
    async with app_db.tenant(actor.organization_id) as session:
        document = Document(
            organization_id=actor.organization_id,
            kind="resume",
            job_id=job.id,
            filename="cv.pdf",
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


async def test_one_email_makes_one_candidate_across_resumes_and_jobs(
    app_db: Database, admin_engine: AsyncEngine, acme: Actor
) -> None:
    first_job, second_job = await new_job(app_db, acme), await new_job(app_db, acme, "Analyst")
    first = await build(
        app_db, acme, await resume(app_db, acme, first_job), result("Asha Rao", "asha@x.test")
    )
    second = await build(
        app_db,
        acme,
        await resume(app_db, acme, second_job, "b" * 64),
        result("Asha R.", "ASHA@x.test", skills=("Go",)),
    )
    assert second.id == first.id

    async with app_db.tenant(acme.organization_id) as session:
        applications = (await session.scalars(select(Application))).all()
        assert {a.job_id for a in applications} == {first_job.id, second_job.id}
        assert all(a.stage == "parsed" for a in applications)
        skills = (await session.scalars(select(CandidateSkill.name))).all()
        assert skills == ["Go"]  # the latest resume's
        candidate = await session.get_one(Candidate, first.id)
        assert candidate.headline == "Senior Engineer at Acme Software"
        assert candidate.embedding is not None
    async with admin_engine.connect() as conn:
        actions = (
            await conn.execute(
                text("SELECT action FROM audit_logs WHERE organization_id = :org ORDER BY seq"),
                {"org": acme.organization_id},
            )
        ).scalars()
        assert [a for a in actions if a.startswith("candidate.")] == [
            "candidate.created",
            "candidate.merged",
        ]


async def test_skills_are_normalised_to_the_taxonomy(app_db: Database, acme: Actor) -> None:
    job = await new_job(app_db, acme)
    candidate = await build(app_db, acme, await resume(app_db, acme, job), result("Asha Rao"))
    async with app_db.tenant(acme.organization_id) as session:
        rows = (
            await session.scalars(
                select(CandidateSkill)
                .where(CandidateSkill.candidate_id == candidate.id)
                .order_by(CandidateSkill.position)
            )
        ).all()
    assert [(row.name, row.skill_id is not None, float(row.years or 0)) for row in rows] == [
        ("Python", True, 4.0),
        ("Kubernetes", True, 4.0),
    ]


async def test_a_phone_written_differently_matches(app_db: Database, acme: Actor) -> None:
    job = await new_job(app_db, acme)
    first = await build(
        app_db, acme, await resume(app_db, acme, job), result("Ravi", phone="+91 98765 43210")
    )
    async with app_db.tenant(acme.organization_id) as session:
        found = await dedupe.match(session, email=None, phone="098765-43210", name="Ravi Kumar")
    assert (found.candidate and found.candidate.id, found.reason) == (first.id, "phone")


async def test_a_near_identical_name_with_another_email_is_flagged_not_merged(
    app_db: Database, acme: Actor
) -> None:
    job = await new_job(app_db, acme)
    first = await build(
        app_db, acme, await resume(app_db, acme, job), result("Meera Iyer", "meera@x.test")
    )
    async with app_db.tenant(acme.organization_id) as session:
        same = await dedupe.match(session, email=None, phone=None, name="Meera  Iyer")
        other = await dedupe.match(
            session, email="meera.iyer@y.test", phone=None, name="Meera Iyer"
        )
    assert (same.candidate and same.candidate.id, same.reason) == (first.id, "name")
    assert (other.candidate, other.possible_duplicate_of) == (None, first.id)


async def test_a_file_already_parsed_is_found_by_its_hash(app_db: Database, acme: Actor) -> None:
    job = await new_job(app_db, acme)
    document = await resume(app_db, acme, job, "c" * 64)
    await build(app_db, acme, document, result("Asha Rao", "asha@x.test"))
    async with app_db.tenant(acme.organization_id) as session:
        (await session.get_one(Document, document.id)).status = "parsed"
    async with app_db.tenant(acme.organization_id) as session:
        copy = await dedupe.parsed_copy(session, "c" * 64)
        assert copy is not None and copy.id == document.id
        assert await dedupe.parsed_copy(session, "d" * 64) is None


async def test_a_team_limited_user_sees_candidates_of_jobs_they_reach(
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
    other_job = await new_job(app_db, acme, "Other job")
    reachable = await build(
        app_db, acme, await resume(app_db, acme, team_job), result("Asha Rao", "asha@x.test")
    )
    hidden = await build(
        app_db,
        acme,
        await resume(app_db, acme, other_job, "e" * 64),
        result("Ravi Kumar", "ravi@x.test"),
    )

    async with app_db.tenant(acme.organization_id) as session:
        scope = await resource_scope(session, limited.user_id)
        seen = (
            await session.scalars(candidates.candidates_statement(scope, CandidateFilters()))
        ).all()
        assert [c.id for c in seen] == [reachable.id]
        with pytest.raises(NotFound):
            await candidates.get_candidate(session, hidden.id, scope)
        detail = await candidates.get_candidate(session, reachable.id, scope)
        assert [job.title for _, job in detail.applications] == ["Team job"]
        wide = await resource_scope(session, acme.user_id)
        searched = (
            await session.scalars(
                candidates.candidates_statement(wide, CandidateFilters(query="ravi@"))
            )
        ).all()
        assert [c.id for c in searched] == [hidden.id]
