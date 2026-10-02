"""Custom roles and the permission catalogue over HTTP (plan Task 8)."""

from collections.abc import Awaitable, Callable
from uuid import UUID

import pytest
from httpx import AsyncClient

from hirevion_core.identity.permissions import ASSIGNABLE_PERMISSIONS

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]


@pytest.fixture
async def acme(make_organization: MakeOrganization) -> UUID:
    return await make_organization("Acme")


@pytest.fixture
async def admin(signed_in, acme: UUID, make_user) -> AsyncClient:
    return await signed_in(acme, await make_user(acme, roles=["org_admin"]))


async def test_a_custom_role_from_creation_to_deletion(admin: AsyncClient) -> None:
    created = await admin.post(
        "/api/v1/roles",
        json={
            "name": "Talent sourcer",
            "description": "Finds people",
            "permissions": ["jobs.view", "candidates.view"],
        },
    )
    assert created.status_code == 201
    role = created.json()
    assert (role["key"], role["system"], role["member_count"]) == (None, False, 0)
    assert role["permissions"] == ["jobs.view", "candidates.view", "account.manage"]

    listed = (await admin.get("/api/v1/roles")).json()
    assert [r["name"] for r in listed][-1] == "Talent sourcer"
    assert listed[0]["key"] == "org_admin" and listed[0]["system"] is True

    changed = await admin.patch(
        f"/api/v1/roles/{role['id']}", json={"permissions": ["jobs.view"], "name": "Sourcer"}
    )
    assert (changed.json()["name"], changed.json()["permissions"]) == (
        "Sourcer",
        ["jobs.view", "account.manage"],
    )
    assert (await admin.delete(f"/api/v1/roles/{role['id']}")).status_code == 204
    assert len((await admin.get("/api/v1/roles")).json()) == 4


async def test_role_problems(admin: AsyncClient) -> None:
    built_in = (await admin.get("/api/v1/roles")).json()[1]
    refused = await admin.patch(f"/api/v1/roles/{built_in['id']}", json={"name": "Talent"})
    assert (refused.status_code, refused.json()["code"]) == (409, "role-system")

    clash = await admin.post(
        "/api/v1/roles", json={"name": "RECRUITER", "permissions": ["jobs.view"]}
    )
    assert (clash.status_code, clash.json()["code"]) == (409, "name-taken")

    platform = await admin.post(
        "/api/v1/roles", json={"name": "Odd", "permissions": ["platform.view"]}
    )
    assert (platform.status_code, platform.json()["code"]) == (422, "unknown-permission")
    assert platform.json()["errors"][0]["pointer"] == "#/permissions"


async def test_the_catalogue_has_no_platform_permissions(admin: AsyncClient) -> None:
    catalogue = (await admin.get("/api/v1/permissions")).json()
    assert [entry["name"] for entry in catalogue] == list(ASSIGNABLE_PERMISSIONS)
    assert {"name": "admin.users.manage", "area": "admin"} in catalogue
