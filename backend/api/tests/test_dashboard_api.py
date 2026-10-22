"""The recruitment dashboard's figures from real data (PRD §10), under its seven filters (D1).

The world below is a small seed: five jobs, four of them open or paused with a candidate each, and
one with an interview that has just completed (and its proctoring events). Every figure is read
back through the HTTP route, the way the page reads it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.ids import uuid7

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]

EVERYTHING = {
    "open_jobs": 3,
    "active_candidates": 3,
    "screened": 2,
    "shortlisted": 1,
    "in_pipeline": 3,
    "interviews_scheduled": 1,
    "live_interviews": 0,
    "completed_interviews": 1,
    "pending_reviews": 1,
    "proctoring_alerts": 8,
}


@dataclass
class World:
    org: UUID
    recruiter_a: UUID
    recruiter_b: UUID
    department_one: UUID
    department_two: UUID
    team: UUID
    shortlisted_job: UUID
    review_job: UUID
    rejected_job: UUID
    completed_job: UUID
    member: UUID
    """A user who belongs to the team (and is limited to it)."""


async def run(engine: AsyncEngine, sql: str, **values: Any) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(sql), values)


async def screen(engine: AsyncEngine, org: UUID, hiring: Any) -> None:
    result = uuid7()
    await run(
        engine,
        "INSERT INTO screening_results (id, organization_id, application_id, job_id, "
        "candidate_id, cache_key, score) VALUES (:id, :org, :app, :job, :candidate, :key, 80)",
        id=result,
        org=org,
        app=hiring.application_id,
        job=hiring.job_id,
        candidate=hiring.candidate_id,
        key=f"seed-{result}",
    )
    await run(
        engine,
        "UPDATE applications SET screening_result_id = :result WHERE id = :app",
        result=result,
        app=hiring.application_id,
    )


async def invite(engine: AsyncEngine, hiring: Any, recruiter: UUID, team: UUID) -> None:
    """An interview that has been sent to the candidate, owned by the job's recruiter and team."""
    now = datetime.now(UTC)
    await run(
        engine,
        "INSERT INTO interviews (id, organization_id, number, application_id, candidate_id, "
        "job_id, template_id, template_version, status, starts_at, expires_at, "
        "duration_minutes, invited_at, recruiter_id, team_id) VALUES (:id, :org, 1000, :app, "
        ":candidate, :job, :template, 1, 'invited', :starts, :expires, 45, :starts, :r, :t)",
        id=uuid7(),
        org=hiring.organization_id,
        app=hiring.application_id,
        candidate=hiring.candidate_id,
        job=hiring.job_id,
        template=hiring.template_id,
        starts=now + timedelta(days=1),
        expires=now + timedelta(days=3),
        r=recruiter,
        t=team,
    )


@pytest.fixture
async def world(
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user,
    make_hiring,
    make_completed_interview,
    add_telemetry,
) -> World:
    org = await make_organization("Acme")
    recruiter_a = await make_user(org, roles=["recruiter"])
    recruiter_b = await make_user(org, roles=["recruiter"])
    member = await make_user(org, roles=["recruiter"])
    department_one, department_two, team = uuid7(), uuid7(), uuid7()
    await run(
        admin_engine,
        "INSERT INTO departments (id, organization_id, name) VALUES (:one, :org, 'Platform'), "
        "(:two, :org, 'Data')",
        one=department_one,
        two=department_two,
        org=org,
    )
    await run(
        admin_engine,
        "INSERT INTO teams (id, organization_id, name, department_id) "
        "VALUES (:team, :org, 'Core', :department)",
        team=team,
        org=org,
        department=department_one,
    )
    await run(
        admin_engine,
        "INSERT INTO team_members (organization_id, team_id, user_id) VALUES (:org, :team, :user)",
        org=org,
        team=team,
        user=member,
    )
    await run(admin_engine, "UPDATE users SET access_scope = 'teams' WHERE id = :id", id=member)

    # J1: open, Platform / Core, recruiter A; a shortlisted, screened candidate with an invited
    # interview.
    one = await make_hiring(org, recruiter_id=recruiter_a)
    await run(
        admin_engine,
        "UPDATE jobs SET department_id = :d, team_id = :t WHERE id = :job",
        d=department_one,
        t=team,
        job=one.job_id,
    )
    await run(
        admin_engine,
        "UPDATE applications SET hiring_status = 'shortlisted' WHERE id = :app",
        app=one.application_id,
    )
    await screen(admin_engine, org, one)
    await invite(admin_engine, one, recruiter_a, team)

    # J2: open, Data, recruiter B; a screened candidate still under review.
    two = await make_hiring(org, recruiter_id=recruiter_b)
    await run(
        admin_engine,
        "UPDATE jobs SET department_id = :d WHERE id = :job",
        d=department_two,
        job=two.job_id,
    )
    await screen(admin_engine, org, two)

    # J3: paused, recruiter A; a candidate who was rejected before screening.
    three = await make_hiring(org, recruiter_id=recruiter_a, job_status="paused")
    await run(
        admin_engine,
        "UPDATE applications SET hiring_status = 'rejected' WHERE id = :app",
        app=three.application_id,
    )

    # J4: open; a candidate whose interview has completed, with the proctoring events a desktop
    # run leaves, waiting for a person to decide.
    scene = await make_completed_interview(org)
    await add_telemetry(scene)
    await run(
        admin_engine,
        "UPDATE applications SET hiring_status = 'interview_completed' WHERE id = :app",
        app=scene.hiring.application_id,
    )
    return World(
        org=org,
        recruiter_a=recruiter_a,
        recruiter_b=recruiter_b,
        department_one=department_one,
        department_two=department_two,
        team=team,
        shortlisted_job=one.job_id,
        review_job=two.job_id,
        rejected_job=three.job_id,
        completed_job=scene.hiring.job_id,
        member=member,
    )


@pytest.fixture
async def admin(signed_in, world: World, make_user) -> AsyncClient:
    return await signed_in(world.org, await make_user(world.org, roles=["org_admin"]))


async def figures(client: AsyncClient, **filters: str) -> dict[str, Any]:
    response = await client.get("/api/v1/dashboard", params=filters)
    assert response.status_code == 200, response.text
    return dict(response.json())


async def test_the_figures_are_counted_from_real_data(admin: AsyncClient, world: World) -> None:
    assert await figures(admin) == EVERYTHING


async def test_the_job_filter_narrows_every_figure(admin: AsyncClient, world: World) -> None:
    assert await figures(admin, job=str(world.shortlisted_job)) == {
        "open_jobs": 1,
        "active_candidates": 1,
        "screened": 1,
        "shortlisted": 1,
        "in_pipeline": 1,
        "interviews_scheduled": 1,
        "live_interviews": 0,
        "completed_interviews": 0,
        "pending_reviews": 0,
        "proctoring_alerts": 0,
    }
    completed = await figures(admin, job=str(world.completed_job))
    assert (completed["proctoring_alerts"], completed["pending_reviews"]) == (8, 1)
    assert (completed["screened"], completed["shortlisted"]) == (0, 0)
    assert (await figures(admin, job=str(uuid7())))["open_jobs"] == 0


async def test_a_paused_jobs_rejected_candidate_is_not_active(
    admin: AsyncClient, world: World
) -> None:
    paused = await figures(admin, job=str(world.rejected_job))
    assert (paused["open_jobs"], paused["active_candidates"], paused["in_pipeline"]) == (0, 0, 0)


async def test_department_team_and_recruiter_filters(admin: AsyncClient, world: World) -> None:
    data = await figures(admin, department=str(world.department_two))
    assert (data["open_jobs"], data["active_candidates"], data["screened"]) == (1, 1, 1)
    assert (data["shortlisted"], data["interviews_scheduled"]) == (0, 0)
    team = await figures(admin, team=str(world.team))
    assert (team["open_jobs"], team["shortlisted"], team["interviews_scheduled"]) == (1, 1, 1)
    a = await figures(admin, recruiter=str(world.recruiter_a))
    assert (a["open_jobs"], a["active_candidates"], a["interviews_scheduled"]) == (1, 1, 1)
    b = await figures(admin, recruiter=str(world.recruiter_b))
    assert (b["open_jobs"], b["screened"], b["shortlisted"]) == (1, 1, 0)


async def test_the_candidate_status_filter(admin: AsyncClient, world: World) -> None:
    data = await figures(admin, candidateStatus="shortlisted")
    assert data == {
        "open_jobs": 1,
        "active_candidates": 1,
        "screened": 1,
        "shortlisted": 1,
        "in_pipeline": 1,
        "interviews_scheduled": 1,
        "live_interviews": 0,
        "completed_interviews": 0,
        "pending_reviews": 0,
        "proctoring_alerts": 0,
    }
    waiting = await figures(admin, candidateStatus="interview_completed")
    assert (waiting["pending_reviews"], waiting["completed_interviews"]) == (1, 1)
    assert (waiting["proctoring_alerts"], waiting["screened"]) == (8, 0)
    rejected = await figures(admin, candidateStatus="rejected")
    assert (rejected["active_candidates"], rejected["in_pipeline"]) == (0, 0)


async def test_the_interview_status_filter(admin: AsyncClient, world: World) -> None:
    invited = await figures(admin, interviewStatus="invited")
    assert (invited["interviews_scheduled"], invited["completed_interviews"]) == (1, 0)
    assert (invited["pending_reviews"], invited["proctoring_alerts"]) == (0, 0)
    assert (invited["active_candidates"], invited["open_jobs"]) == (1, 1)
    completed = await figures(admin, interviewStatus="completed")
    assert (completed["completed_interviews"], completed["interviews_scheduled"]) == (1, 0)
    assert (completed["pending_reviews"], completed["proctoring_alerts"]) == (1, 8)


async def test_the_date_filter(admin: AsyncClient, world: World) -> None:
    now = datetime.now(UTC)
    today = await figures(
        admin,
        **{
            "from": (now - timedelta(days=1)).isoformat(),
            "to": (now + timedelta(days=1)).isoformat(),
        },
    )
    assert today["open_jobs"] == 3 and today["active_candidates"] == 3
    future = await figures(admin, **{"from": (now + timedelta(days=30)).isoformat()})
    assert future == dict.fromkeys(EVERYTHING, 0)
    past = await figures(admin, to=(now - timedelta(days=30)).isoformat())
    assert past == dict.fromkeys(EVERYTHING, 0)


async def test_a_reader_limited_to_a_team_sees_only_that_teams_work(
    signed_in, world: World
) -> None:
    member = await signed_in(world.org, world.member)
    data = await figures(member)
    assert data["open_jobs"] == 1
    assert (data["active_candidates"], data["screened"], data["shortlisted"]) == (1, 1, 1)
    assert (data["interviews_scheduled"], data["proctoring_alerts"]) == (1, 0)


async def test_a_reviewer_sees_only_the_figures_of_what_they_may_read(
    signed_in, world: World, make_user
) -> None:
    interviewer = await signed_in(world.org, await make_user(world.org, roles=["interviewer"]))
    data = await figures(interviewer)
    for jobs_or_candidates in (
        "open_jobs",
        "active_candidates",
        "screened",
        "shortlisted",
        "in_pipeline",
    ):
        assert data[jobs_or_candidates] is None  # no permission to read those
    assert data["interviews_scheduled"] == 0  # only the interviews they review


async def test_another_organisations_work_is_not_counted(
    signed_in, world: World, make_organization: MakeOrganization, make_user
) -> None:
    other = await make_organization("Globex")
    stranger = await signed_in(other, await make_user(other, roles=["org_admin"]))
    assert await figures(stranger) == dict.fromkeys(EVERYTHING, 0)
