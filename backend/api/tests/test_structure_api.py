"""The organisation profile, departments and teams over HTTP (plan Task 6). Who may call them is
the authorisation matrix's job; these check what the routes do."""

from collections.abc import Awaitable, Callable
from uuid import UUID

import pytest
from httpx import AsyncClient

from hirevion_core.identity import PLATFORM_ORGANIZATION_ID
from hirevion_core.ids import uuid7

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]


@pytest.fixture
async def admin(signed_in, make_organization: MakeOrganization, make_user) -> AsyncClient:
    acme = await make_organization("Acme")
    return await signed_in(acme, await make_user(acme, roles=["org_admin"]))


async def test_reading_and_changing_the_profile(admin: AsyncClient) -> None:
    profile = (await admin.get("/api/v1/organization")).json()
    assert (profile["country"], profile["timezone"], profile["default_locale"]) == (
        "IN",
        "Asia/Kolkata",
        "en-IN",
    )
    changed = await admin.patch(
        "/api/v1/organization", json={"timezone": "America/New_York", "website": None}
    )
    assert changed.status_code == 200
    assert changed.json()["timezone"] == "America/New_York"
    assert changed.json()["name"] == profile["name"]


async def test_an_unknown_time_zone_points_at_the_field(admin: AsyncClient) -> None:
    answer = await admin.patch("/api/v1/organization", json={"timezone": "Mars/Base"})
    assert answer.status_code == 422
    assert answer.json()["errors"][0]["pointer"] == "#/timezone"


async def test_unknown_profile_fields_are_refused(admin: AsyncClient) -> None:
    answer = await admin.patch("/api/v1/organization", json={"slug": "hijack"})
    assert answer.status_code == 422


async def test_the_platform_has_no_profile(signed_in, make_user) -> None:
    super_admin = await signed_in(
        PLATFORM_ORGANIZATION_ID, await make_user(PLATFORM_ORGANIZATION_ID, roles=["super_admin"])
    )
    answer = await super_admin.get("/api/v1/organization")
    assert (answer.status_code, answer.json()["code"]) == (403, "platform-organization")


async def test_departments(admin: AsyncClient) -> None:
    created = await admin.post(
        "/api/v1/departments", json={"name": "Engineering", "description": "Builders"}
    )
    assert created.status_code == 201
    department = created.json()
    assert (department["name"], department["archived_at"]) == ("Engineering", None)

    clash = await admin.post("/api/v1/departments", json={"name": "engineering"})
    assert (clash.status_code, clash.json()["code"]) == (409, "name-taken")

    archived = await admin.patch(f"/api/v1/departments/{department['id']}", json={"archived": True})
    assert archived.json()["archived_at"] is not None
    assert (await admin.get("/api/v1/departments")).json() == []
    everything = await admin.get("/api/v1/departments", params={"include_archived": "true"})
    assert [d["name"] for d in everything.json()] == ["Engineering"]

    missing = await admin.patch(f"/api/v1/departments/{uuid7()}", json={"name": "Nope"})
    assert (missing.status_code, missing.json()["code"]) == (404, "department-not-found")


async def test_a_create_is_answered_once_per_idempotency_key(admin: AsyncClient) -> None:
    headers = {"Idempotency-Key": "department-0001"}
    first = await admin.post("/api/v1/departments", json={"name": "Sales"}, headers=headers)
    again = await admin.post("/api/v1/departments", json={"name": "Sales"}, headers=headers)
    assert (first.status_code, again.status_code) == (201, 201)
    assert first.json() == again.json()
    assert len((await admin.get("/api/v1/departments")).json()) == 1


async def test_teams_and_their_members(
    admin: AsyncClient, signed_in, make_organization: MakeOrganization, make_user
) -> None:
    department = (await admin.post("/api/v1/departments", json={"name": "Engineering"})).json()
    created = await admin.post(
        "/api/v1/teams",
        json={"name": "Platform hiring", "department_id": department["id"]},
    )
    assert created.status_code == 201
    team = created.json()
    assert (team["department_name"], team["member_count"]) == ("Engineering", 0)

    session = (await admin.get("/api/v1/auth/session")).json()
    acme = UUID(session["organization"]["id"])
    asha = await make_user(acme, name="Asha Rao")
    added = await admin.put(f"/api/v1/teams/{team['id']}/members/{asha}")
    assert added.status_code == 204
    members = (await admin.get(f"/api/v1/teams/{team['id']}/members")).json()
    assert [(m["name"], m["status"]) for m in members] == [("Asha Rao", "active")]
    assert (await admin.get("/api/v1/teams")).json()[0]["member_count"] == 1

    renamed = await admin.patch(f"/api/v1/teams/{team['id']}", json={"name": "Backend hiring"})
    assert renamed.json()["name"] == "Backend hiring"
    assert renamed.json()["member_count"] == 1

    removed = await admin.delete(f"/api/v1/teams/{team['id']}/members/{asha}")
    assert removed.status_code == 204
    assert (await admin.get(f"/api/v1/teams/{team['id']}/members")).json() == []

    globex = await make_organization("Globex")
    outsider = await make_user(globex)
    refused = await admin.put(f"/api/v1/teams/{team['id']}/members/{outsider}")
    assert (refused.status_code, refused.json()["code"]) == (404, "user-not-found")
