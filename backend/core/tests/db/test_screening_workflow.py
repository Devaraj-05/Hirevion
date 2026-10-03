"""Screening in the background, ranking, and recruiter actions (SP-05 Task 4)."""

from collections.abc import Awaitable, Callable, Sequence
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.access.actor import Actor
from hirevion_core.access.errors import Invalid
from hirevion_core.ai import AiServices, build_ai
from hirevion_core.ai.mock import MockLLM
from hirevion_core.ai.settings import AiSettings
from hirevion_core.ai.types import ChatMessage
from hirevion_core.candidates import profiles
from hirevion_core.db.session import Database
from hirevion_core.documents.resume import ResumeResult
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.jobs import jobs
from hirevion_core.jobs.jobs import JobChanges, SkillInput
from hirevion_core.models import Application, ApplicationHistory, Document, Job
from hirevion_core.screening import runner, workflow

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]
PEOPLE = {  # name: (skills, projects score)
    "Asha Rao": (["Python", "Kubernetes"], 90),
    "Ravi Kumar": (["Python"], 60),
    "Meera Iyer": (["Go"], 30),
    "Kiran Das": ([], 10),
}


def assessment(messages: Sequence[ChatMessage]) -> Any:
    sent = messages[-1]["content"]
    # Blind mode leaves no names, so each resume carries a file number instead.
    score = next(
        points
        for index, (_, points) in enumerate(PEOPLE.values())
        if f"Candidate file {index}" in sent
    )
    quoted = {"score": score, "evidence": []}
    return {
        "roles": quoted,
        "projects": quoted,
        "domain": quoted,
        "education": {"score": 100, "evidence": []},
        "location": {"score": 100, "evidence": []},
    }


@pytest.fixture
async def acme(make_organization: MakeOrganization, make_user) -> Actor:
    organization = await make_organization("Acme")
    user = await make_user(organization, roles=["recruiter"])
    return Actor(user, organization, frozenset(permissions_for(["recruiter"])))


@pytest.fixture
def ai(app_db: Database) -> AiServices:
    services = build_ai(AiSettings(profile="mock"), app_db)
    assert isinstance(services.llm, MockLLM)
    services.llm.scripted["screening.assess"] = assessment
    return services


async def job_with_candidates(app_db: Database, acme: Actor) -> Job:
    async with app_db.tenant(acme.organization_id) as session:
        job = await jobs.create_job(
            session,
            acme,
            JobChanges(
                title="Backend Engineer",
                skills=[SkillInput("Python"), SkillInput("Kubernetes")],
            ),
        )
        for index, (name, (skills, _)) in enumerate(PEOPLE.items()):
            document = Document(
                organization_id=acme.organization_id,
                kind="resume",
                job_id=job.id,
                sha256=f"{index:064d}",
                text=f"Candidate file {index}\n\nSkills\n{', '.join(skills)}",
                status="parsed",
                created_by=acme.user_id,
            )
            session.add(document)
            await session.flush()
            profile = {
                "name": {"value": name, "quote": name},
                "email": {"value": f"{name.split()[0].lower()}@x.test", "quote": "x"},
                "skills": [{"name": skill, "quote": skill} for skill in skills],
                "positions": [],
            }
            await profiles.build(
                session, document, ResumeResult(profile, 0, "fake"), flags={}, embedding=None
            )
        return job


async def screen_all(app_db: Database, ai: AiServices, acme: Actor, job: Job) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        queued = await runner.request_screening(session, acme, job.id)
    assert queued == 4
    async with app_db.tenant(acme.organization_id) as session:
        ids = (await session.scalars(select(Application.id))).all()
    for application_id in ids:
        await runner.handle_screening_event(
            app_db,
            ai,
            acme.organization_id,
            {"action": "screen", "application_id": str(application_id)},
        )


async def ranked(app_db: Database, acme: Actor, job: Job) -> list[tuple[int | None, str, str]]:
    async with app_db.tenant(acme.organization_id) as session:
        rows = await runner.ranking(session, job.id)
        return [(app.rank, candidate.name, app.stage) for app, _, candidate in rows]


async def test_screening_ranks_the_job_once_everyone_is_screened(
    app_db: Database, admin_engine: AsyncEngine, ai: AiServices, acme: Actor
) -> None:
    job = await job_with_candidates(app_db, acme)
    await screen_all(app_db, ai, acme, job)
    assert await ranked(app_db, acme, job) == [
        (1, "Asha Rao", "ranked"),
        (2, "Ravi Kumar", "ranked"),
        (3, "Meera Iyer", "ranked"),
        (4, "Kiran Das", "ranked"),
    ]
    async with admin_engine.connect() as conn:
        topics = (
            await conn.execute(
                text("SELECT topic FROM outbox_events WHERE organization_id = :org"),
                {"org": acme.organization_id},
            )
        ).scalars()
        assert list(topics).count("screening") == 4


async def test_shortlisting_against_the_ranking_needs_a_reason_and_is_recorded(
    app_db: Database, admin_engine: AsyncEngine, ai: AiServices, acme: Actor
) -> None:
    job = await job_with_candidates(app_db, acme)
    await screen_all(app_db, ai, acme, job)
    async with app_db.tenant(acme.organization_id) as session:
        by_rank = {app.rank: app for app, _, _ in await runner.ranking(session, job.id)}
        last = by_rank[4]
        with pytest.raises(Invalid) as refusal:
            await workflow.act(session, acme, job.id, [last.id], "shortlist")
        assert refusal.value.code == "reason-required"
    async with app_db.tenant(acme.organization_id) as session:
        await workflow.act(session, acme, job.id, [last.id], "shortlist", reason="Strong referral")
        await workflow.act(session, acme, job.id, [by_rank[1].id, by_rank[2].id], "hold")
        history = (
            await session.scalars(
                select(ApplicationHistory)
                .where(ApplicationHistory.application_id == last.id)
                .order_by(ApplicationHistory.created_at)
            )
        ).all()
        assert [(h.action, h.to_stage, h.rank, h.override) for h in history][-1] == (
            "shortlist",
            "shortlisted",
            4,
            True,
        )
        stages = {app.rank: app.stage for app, _, _ in await runner.ranking(session, job.id)}
        assert stages == {1: "on_hold", 2: "on_hold", 3: "ranked", 4: "shortlisted"}
    async with admin_engine.connect() as conn:
        actions = (
            await conn.execute(
                text("SELECT action, details FROM audit_logs WHERE organization_id = :org"),
                {"org": acme.organization_id},
            )
        ).all()
    shortlisted = [details for action, details in actions if action == "application.shortlisted"]
    assert shortlisted[0]["override"] is True and shortlisted[0]["reason"] == "Strong referral"


async def test_rejecting_needs_a_reason_and_assignment_needs_a_member(
    app_db: Database, ai: AiServices, acme: Actor, make_user
) -> None:
    job = await job_with_candidates(app_db, acme)
    await screen_all(app_db, ai, acme, job)
    manager = await make_user(acme.organization_id, roles=["hiring_manager"])
    async with app_db.tenant(acme.organization_id) as session:
        first = (await runner.ranking(session, job.id))[0][0]
        with pytest.raises(Invalid) as refusal:
            await workflow.act(session, acme, job.id, [first.id], "reject")
        assert refusal.value.code == "reason-required"
    async with app_db.tenant(acme.organization_id) as session:
        [assigned] = await workflow.act(
            session, acme, job.id, [first.id], "assign_hiring_manager", user_id=manager
        )
        assert (assigned.hiring_manager_id, assigned.stage) == (manager, "ranked")
        with pytest.raises(Invalid):
            await workflow.act(
                session, acme, job.id, [first.id], "assign_recruiter", user_id=UUID(int=7)
            )
