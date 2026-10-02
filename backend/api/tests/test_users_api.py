"""User administration and invitations over HTTP (plan Task 7)."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.ids import uuid7

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]


async def role_id(engine: AsyncEngine, organization_id: UUID, key: str) -> str:
    async with engine.connect() as conn:
        found = await conn.scalar(
            text("SELECT id FROM roles WHERE organization_id = :org AND key = :key"),
            {"org": organization_id, "key": key},
        )
    return str(found)


def email() -> str:
    return f"invitee-{uuid7().hex[-12:]}@acme.example.test"


@pytest.fixture
async def acme(make_organization: MakeOrganization) -> UUID:
    return await make_organization("Acme")


@pytest.fixture
async def admin(signed_in, acme: UUID, make_user) -> AsyncClient:
    return await signed_in(acme, await make_user(acme, name="Olivia Admin", roles=["org_admin"]))


async def test_inviting_listing_and_reading_users(
    admin: AsyncClient, acme: UUID, admin_engine: AsyncEngine
) -> None:
    recruiter = await role_id(admin_engine, acme, "recruiter")
    team = (await admin.post("/api/v1/teams", json={"name": "Campus"})).json()
    address = email()
    invited = await admin.post(
        "/api/v1/users",
        json={
            "email": address,
            "name": "Asha Rao",
            "role_ids": [recruiter],
            "team_ids": [team["id"]],
            "access_scope": "teams",
        },
    )
    assert invited.status_code == 201
    body: dict[str, Any] = invited.json()
    assert (body["email"], body["status"], body["access_scope"]) == (address, "invited", "teams")
    assert [(r["key"], r["name"]) for r in body["roles"]] == [("recruiter", "Recruiter")]
    assert [t["name"] for t in body["teams"]] == ["Campus"]

    page = (await admin.get("/api/v1/users", params={"status": "invited"})).json()
    assert [u["email"] for u in page["items"]] == [address]
    assert page["next_cursor"] is None
    assert (await admin.get(f"/api/v1/users/{body['id']}")).json() == body


async def test_the_list_pages_by_name(admin: AsyncClient, acme: UUID, make_user) -> None:
    for name in ("Bina", "Chitra", "Dev"):
        await make_user(acme, name=name)
    first = (await admin.get("/api/v1/users", params={"limit": 2})).json()
    assert [u["name"] for u in first["items"]] == ["Bina", "Chitra"]
    second = (
        await admin.get("/api/v1/users", params={"limit": 2, "cursor": first["next_cursor"]})
    ).json()
    assert [u["name"] for u in second["items"]] == ["Dev", "Olivia Admin"]


async def test_invitation_problems_point_at_their_fields(
    admin: AsyncClient, acme: UUID, admin_engine: AsyncEngine, make_user
) -> None:
    taken = email()
    await make_user(acme, email=taken)
    recruiter = await role_id(admin_engine, acme, "recruiter")
    clash = await admin.post(
        "/api/v1/users", json={"email": taken, "name": "Again", "role_ids": [recruiter]}
    )
    assert (clash.status_code, clash.json()["code"]) == (409, "email-taken")
    assert clash.json()["errors"][0]["pointer"] == "#/email"

    no_role = await admin.post(
        "/api/v1/users", json={"email": email(), "name": "X", "role_ids": []}
    )
    assert (no_role.status_code, no_role.json()["code"]) == (422, "roles-required")


async def test_role_changes_need_a_recent_password(
    signed_in, acme: UUID, admin_engine: AsyncEngine, make_user
) -> None:
    stale = await signed_in(acme, await make_user(acme, roles=["org_admin"]), stepped_up=False)
    asha = await make_user(acme, roles=["recruiter"])
    manager = await role_id(admin_engine, acme, "hiring_manager")
    answer = await stale.put(f"/api/v1/users/{asha}/roles", json={"role_ids": [manager]})
    assert (answer.status_code, answer.json()["code"]) == (403, "step-up-required")


async def test_changing_a_user(
    admin: AsyncClient, acme: UUID, admin_engine: AsyncEngine, make_user
) -> None:
    # Signed in before (has a password), so enabling makes her active again, not invited.
    asha = await make_user(
        acme, name="Asha", roles=["recruiter"], password_hash="$argon2id$stand-in"
    )
    manager = await role_id(admin_engine, acme, "hiring_manager")

    renamed = await admin.patch(f"/api/v1/users/{asha}", json={"name": "Asha Rao"})
    assert renamed.json()["name"] == "Asha Rao"
    roles = await admin.put(f"/api/v1/users/{asha}/roles", json={"role_ids": [manager]})
    assert [r["key"] for r in roles.json()["roles"]] == ["hiring_manager"]
    disabled = await admin.post(f"/api/v1/users/{asha}/disable")
    assert disabled.json()["status"] == "disabled"
    enabled = await admin.post(f"/api/v1/users/{asha}/enable")
    assert enabled.json()["status"] == "active"


async def test_resending_and_cancelling_an_invitation(
    admin: AsyncClient, acme: UUID, admin_engine: AsyncEngine
) -> None:
    recruiter = await role_id(admin_engine, acme, "recruiter")
    invited = (
        await admin.post(
            "/api/v1/users", json={"email": email(), "name": "Asha", "role_ids": [recruiter]}
        )
    ).json()
    assert (await admin.post(f"/api/v1/users/{invited['id']}/invitation")).status_code == 204
    assert (await admin.delete(f"/api/v1/users/{invited['id']}")).status_code == 204
    gone = await admin.get(f"/api/v1/users/{invited['id']}")
    assert (gone.status_code, gone.json()["code"]) == (404, "user-not-found")


async def test_the_last_admin_is_kept(admin: AsyncClient, acme: UUID) -> None:
    me = (await admin.get("/api/v1/auth/session")).json()["user"]["id"]
    answer = await admin.post(f"/api/v1/users/{me}/disable")
    assert (answer.status_code, answer.json()["code"]) == (409, "self-disable")
