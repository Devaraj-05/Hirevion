"""Interviews over HTTP (SP-07a Task 6): assign, list, read, invite, reschedule, cancel,
reviewers, the dashboard's figures, the job's template field and the support email."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient

from hirevion_core.ids import uuid7

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]
NOW = datetime.now(UTC).replace(microsecond=0)


def window(days: int = 2) -> dict[str, str]:
    return {
        "starts_at": (NOW + timedelta(days=days)).isoformat(),
        "expires_at": (NOW + timedelta(days=days + 1)).isoformat(),
    }


@pytest.fixture
async def acme(make_organization: MakeOrganization) -> UUID:
    return await make_organization("Acme")


@pytest.fixture
async def recruiter_id(acme: UUID, make_user) -> UUID:
    return UUID(str(await make_user(acme, roles=["recruiter"])))


@pytest.fixture
async def recruiter(signed_in, acme: UUID, recruiter_id: UUID) -> AsyncClient:
    return await signed_in(acme, recruiter_id)


async def create(client: AsyncClient, hiring: Any, **extra: Any) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/interviews",
        json={
            "application_id": str(hiring.application_id),
            "template_id": str(hiring.template_id),
            **window(),
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def test_assigning_one_candidate(
    recruiter: AsyncClient, acme: UUID, recruiter_id: UUID, make_hiring
) -> None:
    hiring = await make_hiring(acme, recruiter_id=recruiter_id)
    body = await create(recruiter, hiring)
    assert body["reference"] == "IV-0001"
    assert body["status"] == "invited"
    assert body["candidate"]["name"] == "Asha Rao"
    assert body["template_version"] == 1 and body["duration_minutes"] == 45
    assert body["policy"]["proctoring_level"] == "standard"
    assert [event["action"] for event in body["events"]] == ["created", "invited"]
    assert [item["kind"] for item in body["invitations"]] == ["invitation"]
    read = await recruiter.get(f"/api/v1/interviews/{body['id']}")
    assert read.status_code == 200 and read.json()["id"] == body["id"]
    # The same candidate can't get a second one while this is active.
    again = await recruiter.post(
        "/api/v1/interviews",
        json={
            "application_id": str(hiring.application_id),
            "template_id": str(hiring.template_id),
            **window(),
        },
    )
    assert again.status_code == 409 and again.json()["code"] == "already-assigned"


async def test_bulk_assignment_lists_the_skipped(
    recruiter: AsyncClient, acme: UUID, recruiter_id: UUID, make_hiring
) -> None:
    ok = await make_hiring(acme, recruiter_id=recruiter_id)
    no_email = await make_hiring(
        acme, recruiter_id=recruiter_id, template_id=ok.template_id, candidate_email=None
    )
    response = await recruiter.post(
        "/api/v1/interviews/bulk",
        json={
            "application_ids": [str(ok.application_id), str(no_email.application_id)],
            "template_id": str(ok.template_id),
            **window(),
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["application_id"] for item in body["created"]] == [str(ok.application_id)]
    assert body["skipped"] == [
        {
            "application_id": str(no_email.application_id),
            "code": "no-email",
            "reason": "The candidate has no email address to invite",
        }
    ]


async def test_the_list_by_tab(
    recruiter: AsyncClient, acme: UUID, recruiter_id: UUID, make_hiring
) -> None:
    hiring = await make_hiring(acme, recruiter_id=recruiter_id)
    await create(recruiter, hiring)
    upcoming = (
        await recruiter.get("/api/v1/interviews", params={"status_group": "upcoming"})
    ).json()
    assert [item["reference"] for item in upcoming["items"]] == ["IV-0001"]
    live = (await recruiter.get("/api/v1/interviews", params={"status_group": "live"})).json()
    assert live["items"] == []
    found = (await recruiter.get("/api/v1/interviews", params={"q": "asha"})).json()
    assert len(found["items"]) == 1


async def test_reschedule_cancel_and_resend(
    recruiter: AsyncClient, acme: UUID, recruiter_id: UUID, make_hiring
) -> None:
    hiring = await make_hiring(acme, recruiter_id=recruiter_id)
    body = await create(recruiter, hiring, invite=False)
    assert body["status"] == "scheduled"
    sent = await recruiter.post(f"/api/v1/interviews/{body['id']}/invitation")
    assert sent.status_code == 200 and sent.json()["status"] == "invited"
    moved = await recruiter.post(
        f"/api/v1/interviews/{body['id']}/reschedule", json={**window(6), "reason": "Exams"}
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["reschedule_count"] == 1
    no_reason = await recruiter.post(f"/api/v1/interviews/{body['id']}/cancel", json={"reason": ""})
    assert no_reason.status_code == 422
    cancelled = await recruiter.post(
        f"/api/v1/interviews/{body['id']}/cancel", json={"reason": "Role filled"}
    )
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["cancel_reason"] == "Role filled"
    late = await recruiter.post(f"/api/v1/interviews/{body['id']}/invitation")
    assert late.status_code == 409 and late.json()["code"] == "not-invitable"


async def test_interviewers_see_only_what_they_review(
    signed_in, recruiter: AsyncClient, acme: UUID, recruiter_id: UUID, make_hiring, make_user
) -> None:
    reviewer = await make_user(acme, roles=["interviewer"])
    hiring = await make_hiring(acme, recruiter_id=recruiter_id)
    mine = await create(recruiter, hiring, reviewer_ids=[str(reviewer)])
    other = await create(
        recruiter,
        await make_hiring(acme, recruiter_id=recruiter_id, template_id=hiring.template_id),
    )
    interviewer = await signed_in(acme, reviewer)
    listed = (await interviewer.get("/api/v1/interviews")).json()["items"]
    assert [item["id"] for item in listed] == [mine["id"]]
    hidden = await interviewer.get(f"/api/v1/interviews/{other['id']}")
    assert hidden.status_code == 404
    changed = await recruiter.put(
        f"/api/v1/interviews/{mine['id']}/reviewers", json={"reviewer_ids": []}
    )
    assert changed.status_code == 200 and changed.json()["reviewers"] == []
    assert (await interviewer.get("/api/v1/interviews")).json()["items"] == []


async def test_other_organisations_interviews_dont_exist(
    signed_in, acme: UUID, recruiter: AsyncClient, make_organization, make_user, make_hiring
) -> None:
    globex = await make_organization("Globex")
    theirs = await make_hiring(globex)
    their_recruiter = await signed_in(globex, theirs.recruiter_id)
    body = await create(their_recruiter, theirs)
    assert (await recruiter.get(f"/api/v1/interviews/{body['id']}")).status_code == 404
    response = await recruiter.post(
        "/api/v1/interviews",
        json={
            "application_id": str(theirs.application_id),
            "template_id": str(theirs.template_id),
            **window(),
        },
    )
    assert response.status_code in (404, 422)


async def test_the_dashboard_counts_interviews(
    recruiter: AsyncClient, acme: UUID, recruiter_id: UUID, make_hiring
) -> None:
    hiring = await make_hiring(acme, recruiter_id=recruiter_id)
    await create(recruiter, hiring)
    figures = (await recruiter.get("/api/v1/dashboard")).json()
    assert figures == {
        "interviews_scheduled": 1,
        "live_interviews": 0,
        "completed_interviews": 0,
        "pending_reviews": 0,
    }
    filtered = (await recruiter.get("/api/v1/dashboard", params={"job": str(uuid7())})).json()
    assert filtered["interviews_scheduled"] == 0


async def test_a_job_names_its_interview_template(
    recruiter: AsyncClient, acme: UUID, recruiter_id: UUID, make_hiring
) -> None:
    hiring = await make_hiring(acme, recruiter_id=recruiter_id)
    response = await recruiter.patch(
        f"/api/v1/jobs/{hiring.job_id}", json={"interview_template_id": str(hiring.template_id)}
    )
    assert response.status_code == 200, response.text
    assert response.json()["interview_template_id"] == str(hiring.template_id)
    assert response.json()["interview_template_name"]
    unknown = await recruiter.patch(
        f"/api/v1/jobs/{hiring.job_id}", json={"interview_template_id": str(uuid7())}
    )
    assert unknown.status_code == 422 and unknown.json()["code"] == "invalid-template"
    # With the job's template, the interview needs none named.
    created = await recruiter.post(
        "/api/v1/interviews", json={"application_id": str(hiring.application_id), **window()}
    )
    assert created.status_code == 201, created.text


async def test_the_support_email_is_part_of_the_profile(signed_in, acme: UUID, make_user) -> None:
    admin = await signed_in(acme, await make_user(acme, roles=["org_admin"]))
    response = await admin.patch(
        "/api/v1/organization", json={"support_email": "help@acme.example.test"}
    )
    assert (
        response.status_code == 200 and response.json()["support_email"] == "help@acme.example.test"
    )
    bad = await admin.patch("/api/v1/organization", json={"support_email": "not an email"})
    assert bad.status_code == 422
    cleared = await admin.patch("/api/v1/organization", json={"support_email": None})
    assert cleared.json()["support_email"] is None


async def test_a_bad_window_is_unprocessable_whichever_template_is_used(
    recruiter: AsyncClient, admin_engine, acme: UUID, recruiter_id: UUID, make_hiring
) -> None:
    from sqlalchemy import text

    hiring = await make_hiring(acme, recruiter_id=recruiter_id)
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE jobs SET interview_template_id = :t WHERE id = :j"),
            {"t": hiring.template_id, "j": hiring.job_id},
        )
    past = {
        "starts_at": (NOW - timedelta(days=2)).isoformat(),
        "expires_at": (NOW - timedelta(days=1)).isoformat(),
    }
    for extra in ({}, {"template_id": str(hiring.template_id)}):
        response = await recruiter.post(
            "/api/v1/interviews",
            json={"application_id": str(hiring.application_id), **past, **extra},
        )
        assert response.status_code == 422, response.text
        assert response.json()["code"] == "window-past"


async def test_a_job_keeps_a_default_template_that_was_archived_since(
    recruiter: AsyncClient, acme: UUID, recruiter_id: UUID, make_hiring
) -> None:
    hiring = await make_hiring(acme, recruiter_id=recruiter_id)
    job = f"/api/v1/jobs/{hiring.job_id}"
    template = str(hiring.template_id)
    assert (await recruiter.patch(job, json={"interview_template_id": template})).status_code == 200
    archived = await recruiter.post(f"/api/v1/interview-templates/{template}/archive")
    assert archived.status_code == 200
    edited = await recruiter.patch(
        job, json={"title": "Senior Backend Engineer", "interview_template_id": template}
    )
    assert edited.status_code == 200, edited.text
