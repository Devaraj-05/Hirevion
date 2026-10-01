"""The sign-in API (`/api/v1/auth/*`) end to end over HTTP, against PostgreSQL and Valkey."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_api.app import create_app
from hirevion_api.auth.cookies import CSRF_COOKIE, SESSION_COOKIE
from hirevion_api.settings import ApiSettings
from hirevion_core.db.session import Database
from hirevion_core.identity.passwords import hash_password
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.ids import uuid7

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]
ORIGIN = "https://app.hirevion.localhost"
PASSWORD = "correct horse battery staple"  # noqa: S105 (a test input)
NEW_PASSWORD = "a brand new long passphrase"  # noqa: S105 (a test input)


@pytest.fixture
def app(app_db: Database, valkey: Redis) -> FastAPI:
    return create_app(
        ApiSettings(allowed_origins=ORIGIN, run_workers=False),
        db=app_db,
        redis=valkey,
        identity=IdentitySettings(hibp_enabled=False, web_origin=ORIGIN),
    )


@pytest.fixture
async def browser(app: FastAPI) -> Callable[[], Awaitable[AsyncClient]]:
    """Makes browser-like clients: HTTPS (the cookies are Secure), with the app's Origin."""
    clients: list[AsyncClient] = []

    async def make() -> AsyncClient:
        client = AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url=ORIGIN,
            headers={"Origin": ORIGIN},
        )
        clients.append(client)
        return client

    yield make  # type: ignore[misc]
    for client in clients:
        await client.aclose()


def email() -> str:
    return f"user-{uuid7().hex[-12:]}@acme.example.test"


async def outbox_mail(engine: AsyncEngine, address: str) -> list[dict[str, Any]]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT payload FROM outbox_events WHERE topic = 'mail' "
                "AND payload->>'to' = :to ORDER BY created_at"
            ),
            {"to": address},
        )
        return [row.payload for row in rows]


def link_token(mail: dict[str, Any]) -> str:
    return str(mail["context"]["link"]).rsplit("/", 1)[1]


async def sign_in(client: AsyncClient, address: str, password: str = PASSWORD) -> Response:
    return await client.post("/api/v1/auth/login", json={"email": address, "password": password})


def csrf(client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies[CSRF_COOKIE]}


async def recruiter(make_organization: MakeOrganization, make_user) -> tuple[UUID, str]:
    acme = await make_organization("Acme")
    address = email()
    await make_user(
        acme,
        email=address,
        name="Ravi Kumar",
        password_hash=hash_password(PASSWORD),
        roles=["recruiter"],
    )
    return acme, address


async def test_signing_in_sets_both_cookies_and_the_session_answers(
    browser, make_organization: MakeOrganization, make_user
) -> None:
    acme, address = await recruiter(make_organization, make_user)
    client = await browser()
    response = await sign_in(client, address)
    assert response.status_code == 204
    cookies = response.headers.get_list("set-cookie")
    session = next(c for c in cookies if c.startswith(f"{SESSION_COOKIE}="))
    token = next(c for c in cookies if c.startswith(f"{CSRF_COOKIE}="))
    for attribute in ("Secure", "Path=/", "SameSite=lax"):
        assert attribute in session and attribute in token
    assert "HttpOnly" in session and "HttpOnly" not in token
    assert "Domain" not in session

    body = (await client.get("/api/v1/auth/session")).json()
    assert body["user"]["email"] == address and body["user"]["name"] == "Ravi Kumar"
    assert body["organization"]["id"] == str(acme)
    assert body["roles"] == ["recruiter"]
    assert body["custom_roles"] == []
    assert body["permissions"] == permissions_for(["recruiter"])


async def test_the_session_reports_custom_roles_and_their_permissions(
    browser, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_user
) -> None:
    acme, address = await recruiter(make_organization, make_user)
    role_id = uuid7()
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO roles (id, organization_id, name) VALUES (:id, :org, 'Sourcer')"),
            {"id": role_id, "org": acme},
        )
        await conn.execute(
            text(
                "INSERT INTO role_permissions (organization_id, role_id, permission) "
                "VALUES (:org, :role, 'admin.teams.manage')"
            ),
            {"org": acme, "role": role_id},
        )
        await conn.execute(
            text(
                "INSERT INTO user_roles (organization_id, user_id, role_id) "
                "SELECT :org, id, :role FROM users WHERE email = :email"
            ),
            {"org": acme, "role": role_id, "email": address},
        )
    client = await browser()
    await sign_in(client, address)

    body = (await client.get("/api/v1/auth/session")).json()
    assert body["roles"] == ["recruiter"]
    assert body["custom_roles"] == ["Sourcer"]
    assert body["permissions"] == permissions_for(["recruiter"], ["admin.teams.manage"])


async def test_signing_out_clears_the_session(
    browser, make_organization: MakeOrganization, make_user
) -> None:
    _, address = await recruiter(make_organization, make_user)
    client = await browser()
    await sign_in(client, address)
    assert (await client.post("/api/v1/auth/logout", headers=csrf(client))).status_code == 204
    assert SESSION_COOKIE not in client.cookies
    answer = await client.get("/api/v1/auth/session")
    assert answer.status_code == 401 and answer.json()["code"] == "unauthenticated"


async def test_a_wrong_password_and_an_unknown_email_get_identical_answers(
    browser, make_organization: MakeOrganization, make_user
) -> None:
    _, address = await recruiter(make_organization, make_user)
    client = await browser()
    wrong = await sign_in(client, address, "not the right password at all")
    unknown = await sign_in(client, "nobody@example.test")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["code"] == "invalid-credentials"
    assert wrong.content == unknown.content


async def test_repeated_failures_are_answered_with_a_wait(
    browser, make_organization: MakeOrganization, make_user
) -> None:
    _, address = await recruiter(make_organization, make_user)
    client = await browser()
    for _ in range(4):
        assert (await sign_in(client, address, "wrong password attempt")).status_code == 401
    locked = await sign_in(client, address, "wrong password attempt")
    assert locked.status_code == 429 and locked.headers["Retry-After"] == "60"
    # The form says how long to wait.
    assert locked.json()["retry_after"] == 60
    assert (await sign_in(client, address)).status_code == 429


async def test_forgot_password_answers_the_same_for_anyone(
    browser, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_user
) -> None:
    _, address = await recruiter(make_organization, make_user)
    client = await browser()
    known = await client.post("/api/v1/auth/password/forgot", json={"email": address})
    unknown = await client.post("/api/v1/auth/password/forgot", json={"email": "no@example.test"})
    assert known.status_code == unknown.status_code == 202
    assert known.content == unknown.content
    assert len(await outbox_mail(admin_engine, address)) == 1


async def test_resetting_a_password(
    browser, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_user
) -> None:
    _, address = await recruiter(make_organization, make_user)
    before = await browser()
    await sign_in(before, address)

    client = await browser()
    await client.post("/api/v1/auth/password/forgot", json={"email": address})
    [mail] = await outbox_mail(admin_engine, address)
    token = link_token(mail)
    reset = await client.post(
        "/api/v1/auth/password/reset", json={"token": token, "password": NEW_PASSWORD}
    )
    assert reset.status_code == 204
    assert token not in reset.text and NEW_PASSWORD not in reset.text

    assert (await before.get("/api/v1/auth/session")).status_code == 401
    assert (await sign_in(client, address, PASSWORD)).status_code == 401
    assert (await sign_in(client, address, NEW_PASSWORD)).status_code == 204
    # Now signed in, the client sends the CSRF header, as the web app's client always does.
    again = await client.post(
        "/api/v1/auth/password/reset",
        json={"token": token, "password": NEW_PASSWORD},
        headers=csrf(client),
    )
    assert again.status_code == 400 and again.json()["code"] == "invalid-token"


async def test_a_rejected_password_names_each_reason_on_its_field(
    browser, make_organization: MakeOrganization, make_user
) -> None:
    _, address = await recruiter(make_organization, make_user)
    client = await browser()
    await sign_in(client, address)
    short = await client.post(
        "/api/v1/auth/password/change",
        json={"current_password": PASSWORD, "new_password": "too short"},
        headers=csrf(client),
    )
    assert short.status_code == 422 and short.json()["code"] == "password-rejected"
    assert short.json()["errors"] == [{"detail": "too_short", "pointer": "#/new_password"}]

    wrong = await client.post(
        "/api/v1/auth/password/change",
        json={"current_password": "not it at all", "new_password": NEW_PASSWORD},
        headers=csrf(client),
    )
    assert wrong.status_code == 422
    assert wrong.json()["errors"] == [{"detail": "wrong_current", "pointer": "#/current_password"}]

    changed = await client.post(
        "/api/v1/auth/password/change",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=csrf(client),
    )
    assert changed.status_code == 204
    assert (await client.get("/api/v1/auth/session")).status_code == 200


async def test_listing_and_ending_sessions(
    browser, make_organization: MakeOrganization, make_user
) -> None:
    _, address = await recruiter(make_organization, make_user)
    laptop, phone, tablet = await browser(), await browser(), await browser()
    for client in (laptop, phone, tablet):
        await sign_in(client, address)

    listed = (await laptop.get("/api/v1/auth/sessions")).json()
    assert len(listed) == 3
    assert [s["current"] for s in listed].count(True) == 1
    other = next(s["id"] for s in listed if not s["current"])

    ended = await laptop.delete(f"/api/v1/auth/sessions/{other}", headers=csrf(laptop))
    assert ended.status_code == 204
    missing = await laptop.delete(f"/api/v1/auth/sessions/{uuid7()}", headers=csrf(laptop))
    assert missing.status_code == 404

    revoked = await laptop.post("/api/v1/auth/sessions/revoke-others", headers=csrf(laptop))
    assert revoked.status_code == 204
    statuses = [(await c.get("/api/v1/auth/session")).status_code for c in (laptop, phone, tablet)]
    assert statuses == [200, 401, 401]


async def test_changing_the_email_address(
    browser, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_user
) -> None:
    _, address = await recruiter(make_organization, make_user)
    new = email()
    client = await browser()
    await sign_in(client, address)

    wrong = await client.post(
        "/api/v1/auth/email/change",
        json={"new_email": new, "password": "not it at all"},
        headers=csrf(client),
    )
    assert wrong.status_code == 422
    assert wrong.json()["errors"] == [{"detail": "wrong_password", "pointer": "#/password"}]

    asked = await client.post(
        "/api/v1/auth/email/change",
        json={"new_email": new, "password": PASSWORD},
        headers=csrf(client),
    )
    assert asked.status_code == 202
    [verify] = await outbox_mail(admin_engine, new)
    confirmed = await client.post(
        "/api/v1/auth/email/verify", json={"token": link_token(verify)}, headers=csrf(client)
    )
    assert confirmed.status_code == 204
    assert (await client.get("/api/v1/auth/session")).json()["user"]["email"] == new
    reused = await client.post(
        "/api/v1/auth/email/verify", json={"token": link_token(verify)}, headers=csrf(client)
    )
    assert reused.status_code == 400


async def test_an_invited_user_sets_a_first_password(
    browser,
    app_db: Database,
    make_organization: MakeOrganization,
    make_user,
) -> None:
    from datetime import UTC, datetime, timedelta

    from hirevion_core.identity.tokens import issue_token

    acme = await make_organization("Acme")
    address = email()
    gita = await make_user(acme, email=address, status="invited")
    async with app_db.tenant(acme) as session:
        token = await issue_token(
            session,
            organization_id=acme,
            user_id=gita,
            purpose="set_password",
            ttl=timedelta(hours=72),
            now=datetime.now(UTC),
        )
    client = await browser()
    answer = await client.post(
        "/api/v1/auth/password/set", json={"token": token, "password": NEW_PASSWORD}
    )
    assert answer.status_code == 204
    assert (await sign_in(client, address, NEW_PASSWORD)).status_code == 204


async def test_state_changes_without_the_csrf_token_are_refused(
    browser, make_organization: MakeOrganization, make_user
) -> None:
    _, address = await recruiter(make_organization, make_user)
    client = await browser()
    await sign_in(client, address)
    refused = await client.post("/api/v1/auth/sessions/revoke-others")
    assert refused.status_code == 403 and refused.json()["code"] == "csrf-failed"


async def test_stepping_up(browser, make_organization: MakeOrganization, make_user) -> None:
    _, address = await recruiter(make_organization, make_user)
    client = await browser()
    await sign_in(client, address)

    wrong = await client.post(
        "/api/v1/auth/step-up", json={"password": "not my password"}, headers=csrf(client)
    )
    assert wrong.status_code == 422
    assert wrong.json()["errors"] == [{"detail": "wrong_password", "pointer": "#/password"}]

    right = await client.post(
        "/api/v1/auth/step-up", json={"password": PASSWORD}, headers=csrf(client)
    )
    assert right.status_code == 204
    assert (await client.get("/api/v1/auth/session")).status_code == 200


async def test_stepping_up_needs_a_session_and_the_csrf_token(
    browser, make_organization: MakeOrganization, make_user
) -> None:
    _, address = await recruiter(make_organization, make_user)
    anonymous = await browser()
    answer = await anonymous.post("/api/v1/auth/step-up", json={"password": PASSWORD})
    assert answer.status_code == 401

    client = await browser()
    await sign_in(client, address)
    refused = await client.post("/api/v1/auth/step-up", json={"password": PASSWORD})
    assert refused.status_code == 403
    assert refused.json()["code"] == "csrf-failed"
