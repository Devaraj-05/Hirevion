"""The candidate portal's API (`/api/v1/portal/*`, SP-07b; ADR-0022) and the recruiters' view of
candidate requests (`/api/v1/candidate-requests`), over HTTP against PostgreSQL and Valkey."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_api.app import create_app
from hirevion_api.auth.cookies import SESSION_COOKIE
from hirevion_api.portal.cookies import PORTAL_CSRF_COOKIE, PORTAL_SESSION_COOKIE
from hirevion_api.settings import ApiSettings
from hirevion_core.access.actor import Actor
from hirevion_core.access.scope import ResourceScope
from hirevion_core.db.session import Database
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.ids import uuid7
from hirevion_core.interviews import assignment
from hirevion_core.interviews.assignment import Assignment

pytestmark = pytest.mark.db

ORIGIN = "https://app.hirevion.localhost"
PORTAL = "https://candidate.hirevion.localhost"
PASSWORD = "a long candidate passphrase"  # noqa: S105 (a test password)
IDENTITY = IdentitySettings(hibp_enabled=False, web_origin=ORIGIN, candidate_origin=PORTAL)


@pytest.fixture
def app(app_db: Database, valkey: Redis) -> FastAPI:
    return create_app(
        ApiSettings(
            allowed_origins=ORIGIN, portal_origins=PORTAL, run_workers=False, ip_rate_limit=100_000
        ),
        db=app_db,
        redis=valkey,
        identity=IDENTITY,
    )


@pytest.fixture
async def portal(app: FastAPI) -> AsyncIterator[Callable[[], AsyncClient]]:
    """Makes browser-like clients on the portal's host, sending its Origin."""
    clients: list[AsyncClient] = []

    def make() -> AsyncClient:
        client = AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url=PORTAL,
            headers={"Origin": PORTAL},
        )
        clients.append(client)
        return client

    yield make
    for client in clients:
        await client.aclose()


async def post(client: AsyncClient, path: str, body: Any = None, **headers: str) -> Response:
    csrf = client.cookies.get(PORTAL_CSRF_COOKIE)
    sent = {"X-CSRF-Token": csrf} if csrf else {}
    return await client.post(f"/api/v1{path}", json=body, headers={**sent, **headers})


async def invite(app_db: Database, make_hiring: Any, org: UUID) -> tuple[Any, UUID, str]:
    address = f"cand-{uuid7().hex[-10:]}@example.test"
    hiring = await make_hiring(org, candidate_email=address)
    actor = Actor(hiring.recruiter_id, org, frozenset(permissions_for(["recruiter"])))
    now = datetime.now(UTC)
    async with app_db.tenant(org) as session:
        result = await assignment.assign(
            session,
            actor,
            Assignment(
                application_ids=[hiring.application_id],
                template_id=hiring.template_id,
                starts_at=now + timedelta(days=1),
                expires_at=now + timedelta(days=3),
            ),
            ResourceScope(actor.user_id, organization_wide=True, team_ids=frozenset()),
            settings=IDENTITY,
        )
    return hiring, result.created[0].id, address


async def mailed(admin_engine: AsyncEngine, to: str, segment: str) -> str:
    async with admin_engine.connect() as conn:
        payloads = (
            await conn.scalars(
                text(
                    "SELECT payload FROM outbox_events WHERE topic = 'mail' "
                    "AND payload->>'to' = :to ORDER BY created_at DESC"
                ),
                {"to": to},
            )
        ).all()
    for payload in payloads:
        for value in payload["context"].values():
            match = re.search(rf"{segment}([\w-]+)", str(value))
            if match:
                return match.group(1)
    raise AssertionError(f"no {segment} link mailed to {to}")


async def signed_in_candidate(
    portal: Callable[[], AsyncClient],
    app_db: Database,
    admin_engine: AsyncEngine,
    make_hiring: Any,
    org: UUID,
) -> tuple[AsyncClient, Any, UUID, str]:
    """A candidate who followed the invitation's link, set a password and signed in."""
    hiring, interview_id, email = await invite(app_db, make_hiring, org)
    client = portal()
    token = await mailed(admin_engine, email, "/invitation/")
    assert (
        await post(client, "/portal/auth/password/set", {"token": token, "password": PASSWORD})
    ).status_code == 204
    login = await post(client, "/portal/auth/login", {"email": email, "password": PASSWORD})
    assert login.status_code == 204, login.text
    return client, hiring, interview_id, email


async def test_the_invitation_link_then_sign_in_lists_the_interview(
    portal, app_db: Database, admin_engine: AsyncEngine, make_organization, make_hiring
) -> None:
    org = await make_organization("Acme")
    client, _, interview_id, email = await signed_in_candidate(
        portal, app_db, admin_engine, make_hiring, org
    )
    assert client.cookies.get(PORTAL_SESSION_COOKIE)
    assert client.cookies.get(SESSION_COOKIE) is None

    session = await client.get("/api/v1/portal/auth/session")
    assert session.status_code == 200
    assert session.json()["account"]["email"] == email
    assert session.json()["organization"]["name"] == "Acme"

    listed = await client.get("/api/v1/portal/interviews")
    assert listed.status_code == 200
    body = listed.json()
    assert [item["id"] for item in body["interviews"]] == [str(interview_id)]
    item = body["interviews"][0]
    assert item["status"] == "invited" and item["can_take"] is False
    assert item["job_title"] == "Backend Engineer"
    assert body["now"]

    out = await post(client, "/portal/auth/logout")
    assert out.status_code == 204
    assert (await client.get("/api/v1/portal/auth/session")).status_code == 401


async def test_the_portal_session_doesnt_open_recruiter_routes(
    portal, app_db: Database, admin_engine: AsyncEngine, make_organization, make_hiring
) -> None:
    org = await make_organization("Acme")
    client, *_ = await signed_in_candidate(portal, app_db, admin_engine, make_hiring, org)
    assert (await client.get("/api/v1/auth/session")).status_code == 401
    assert (await client.get("/api/v1/interviews")).status_code == 401


async def test_sign_in_refusals_reveal_nothing_and_lock_out(
    portal, app_db: Database, admin_engine: AsyncEngine, make_organization, make_hiring
) -> None:
    org = await make_organization("Acme")
    _, _, _, email = await signed_in_candidate(portal, app_db, admin_engine, make_hiring, org)
    client = portal()
    unknown = await post(
        client, "/portal/auth/login", {"email": "x@example.test", "password": PASSWORD}
    )
    wrong = await post(
        client, "/portal/auth/login", {"email": email, "password": "wrong password!"}
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["code"] == wrong.json()["code"] == "invalid-credentials"
    for _ in range(IDENTITY.lockout_threshold):
        last = await post(client, "/portal/auth/login", {"email": email, "password": "wrong!!!!!"})
    assert last.status_code == 429 and last.headers["Retry-After"]


async def test_set_password_rejections_and_used_links(
    portal, app_db: Database, admin_engine: AsyncEngine, make_organization, make_hiring
) -> None:
    org = await make_organization("Acme")
    _, _, email = await invite(app_db, make_hiring, org)
    client = portal()
    token = await mailed(admin_engine, email, "/invitation/")
    short = await post(client, "/portal/auth/password/set", {"token": token, "password": "short"})
    assert short.status_code == 422 and short.json()["code"] == "password-rejected"
    ok = await post(client, "/portal/auth/password/set", {"token": token, "password": PASSWORD})
    assert ok.status_code == 204
    again = await post(client, "/portal/auth/password/set", {"token": token, "password": PASSWORD})
    assert again.status_code == 400 and again.json()["code"] == "invalid-token"


async def test_forgot_and_reset(
    portal, app_db: Database, admin_engine: AsyncEngine, make_organization, make_hiring
) -> None:
    org = await make_organization("Acme")
    _, _, _, email = await signed_in_candidate(portal, app_db, admin_engine, make_hiring, org)
    client = portal()
    for address in (email, "nobody@example.test"):
        response = await post(client, "/portal/auth/password/forgot", {"email": address})
        assert response.status_code == 202
    token = await mailed(admin_engine, email, "/reset-password/")
    new = "another long candidate passphrase"
    reset = await post(client, "/portal/auth/password/reset", {"token": token, "password": new})
    assert reset.status_code == 204
    login = await post(client, "/portal/auth/login", {"email": email, "password": new})
    assert login.status_code == 204


async def test_requests_from_the_portal_reach_the_recruiter(
    portal,
    signed_in,
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization,
    make_hiring,
) -> None:
    org = await make_organization("Acme")
    client, hiring, interview_id, _ = await signed_in_candidate(
        portal, app_db, admin_engine, make_hiring, org
    )
    created = await post(
        client,
        "/portal/requests",
        {
            "kind": "reschedule",
            "interview_id": str(interview_id),
            "message": "I'm travelling that week",
            "details": {"preferred": "Any weekday after the 20th"},
        },
        **{"Idempotency-Key": f"test-{uuid7()}"},
    )
    assert created.status_code == 201, created.text
    request_id = created.json()["id"]
    assert created.json()["status"] == "open"
    assert created.json()["reference"].startswith("RQ-")
    without_key = await post(client, "/portal/requests", {"kind": "data_access"})
    assert without_key.status_code == 400
    bad = await post(
        client,
        "/portal/requests",
        {"kind": "consent_withdrawal", "details": {"purposes": []}},
        **{"Idempotency-Key": f"test-{uuid7()}"},
    )
    assert bad.status_code == 422 and bad.json()["code"] == "purposes-required"
    mine = await client.get("/api/v1/portal/requests")
    assert [item["id"] for item in mine.json()] == [request_id]

    recruiter = await signed_in(org, hiring.recruiter_id)
    listed = await recruiter.get("/api/v1/candidate-requests", params={"status": "open"})
    assert listed.status_code == 200
    [item] = listed.json()["items"]
    assert item["id"] == request_id
    assert item["kind"] == "reschedule" and item["candidate_name"] == "Asha Rao"
    assert item["interview_reference"].startswith("IV-")
    assert item["details"] == {"preferred": "Any weekday after the 20th"}

    updated = await recruiter.patch(
        f"/api/v1/candidate-requests/{request_id}",
        json={"status": "resolved", "response": "Moved to the 22nd"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["status"] == "resolved"
    again = await recruiter.patch(
        f"/api/v1/candidate-requests/{request_id}", json={"status": "declined"}
    )
    assert again.status_code == 409
    seen = (await client.get("/api/v1/portal/requests")).json()[0]
    assert (seen["status"], seen["response"]) == ("resolved", "Moved to the 22nd")


async def test_portal_pages_need_a_portal_session(portal) -> None:
    client = portal()
    for path in ("/portal/auth/session", "/portal/interviews", "/portal/requests"):
        response = await client.get(f"/api/v1{path}")
        assert response.status_code == 401, path
        assert response.json()["code"] == "unauthenticated"


async def test_notices_and_downloads_are_public(portal) -> None:
    client = portal()
    notices = await client.get("/api/v1/portal/notices")
    assert notices.status_code == 200
    body = notices.json()
    assert len(body["disclosures"]) == 10
    assert [policy["key"] for policy in body["policies"]] == [
        "privacy",
        "recording",
        "proctoring",
        "data-retention",
        "deletion",
        "support",
    ]
    downloads = await client.get("/api/v1/portal/downloads")
    assert downloads.status_code == 200
    assert downloads.json()["system_requirements"]
    assert "download_url" in downloads.json()
