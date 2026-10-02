"""The platform's organisations over HTTP (plan Task 9)."""

import pytest
from httpx import AsyncClient

from hirevion_core.identity import PLATFORM_ORGANIZATION_ID
from hirevion_core.ids import uuid7

pytestmark = pytest.mark.db


@pytest.fixture
async def super_admin(signed_in, make_user) -> AsyncClient:
    user = await make_user(PLATFORM_ORGANIZATION_ID, name="Sam Platform", roles=["super_admin"])
    return await signed_in(PLATFORM_ORGANIZATION_ID, user)


def new_organization(marker: str, name: str) -> dict[str, str]:
    return {
        "name": f"{marker} {name}",
        "slug": f"{name.lower()}-{uuid7().hex[-8:]}",
        "admin_name": "First Admin",
        "admin_email": f"admin-{uuid7().hex[-12:]}@example.test",
    }


async def test_creating_listing_and_paging_organisations(super_admin: AsyncClient) -> None:
    marker = uuid7().hex[-6:]
    created = await super_admin.post(
        "/api/v1/platform/organizations", json=new_organization(marker, "Initech")
    )
    assert created.status_code == 201
    assert (created.json()["status"], created.json()["user_count"]) == ("active", 1)
    for name in ("Hooli", "Umbrella"):
        await super_admin.post(
            "/api/v1/platform/organizations", json=new_organization(marker, name)
        )

    first = (
        await super_admin.get("/api/v1/platform/organizations", params={"q": marker, "limit": 2})
    ).json()
    assert [o["name"] for o in first["items"]] == [f"{marker} Hooli", f"{marker} Initech"]
    second = (
        await super_admin.get(
            "/api/v1/platform/organizations",
            params={"q": marker, "limit": 2, "cursor": first["next_cursor"]},
        )
    ).json()
    assert [o["name"] for o in second["items"]] == [f"{marker} Umbrella"]
    assert second["next_cursor"] is None


async def test_suspending_reactivating_and_inviting_another_admin(
    super_admin: AsyncClient,
) -> None:
    organization = (
        await super_admin.post(
            "/api/v1/platform/organizations", json=new_organization("x", "Initech")
        )
    ).json()
    base = f"/api/v1/platform/organizations/{organization['id']}"
    suspended = await super_admin.post(f"{base}/suspend", json={"reason": "Trial ended"})
    assert suspended.json()["status"] == "suspended"
    reactivated = await super_admin.post(f"{base}/reactivate")
    assert reactivated.json()["status"] == "active"
    invited = await super_admin.post(
        f"{base}/admins",
        json={"name": "Second Admin", "email": f"second-{uuid7().hex[-8:]}@example.test"},
    )
    assert invited.status_code == 204


async def test_platform_problems(super_admin: AsyncClient) -> None:
    platform = f"/api/v1/platform/organizations/{PLATFORM_ORGANIZATION_ID}/suspend"
    refused = await super_admin.post(platform, json={})
    assert (refused.status_code, refused.json()["code"]) == (409, "platform-organization")

    missing = await super_admin.post(f"/api/v1/platform/organizations/{uuid7()}/reactivate")
    assert (missing.status_code, missing.json()["code"]) == (404, "organization-not-found")

    reserved = await super_admin.post(
        "/api/v1/platform/organizations", json={**new_organization("x", "Odd"), "slug": "admin"}
    )
    assert (reserved.status_code, reserved.json()["errors"][0]["pointer"]) == (422, "#/slug")
