"""The authorisation matrix: every API route against every role (master plan §14 SP-02 exit
criterion; ADR-0014).

Every route under /api/v1 is either guarded by `requires(...)` or listed in `UNGUARDED` with a
reason, so a later sub-project can't add an open route by accident. Each guarded route is then
called as each of the five system roles: a role holding none of the route's permissions must
get 403 `forbidden`, and a role holding one must get anything else.
"""

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis

from hirevion_api.app import create_app
from hirevion_api.auth.cookies import CSRF_COOKIE, SESSION_COOKIE
from hirevion_api.authz import UNGUARDED, ApiRoute, api_routes
from hirevion_api.settings import ApiSettings
from hirevion_core.db.session import Database
from hirevion_core.identity import PLATFORM_ORGANIZATION_ID
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.identity.sessions import create_session
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.ids import uuid7

ORIGIN = "https://app.hirevion.localhost"
ROLES = ("super_admin", "org_admin", "recruiter", "hiring_manager", "interviewer")
SETTINGS = ApiSettings(allowed_origins=ORIGIN, run_workers=False, ip_rate_limit=1_000_000)
IDENTITY = IdentitySettings(hibp_enabled=False, web_origin=ORIGIN)

# Listed at import, so each guarded route becomes its own test case.
ROUTES = api_routes(create_app(SETTINGS))
GUARDED = [route for route in ROUTES if route.requirement is not None]


def route_id(route: ApiRoute) -> str:
    return f"{route.method} {route.path}"


# Who may call what, written out so that any change to it shows up in review: route → (the
# permissions, any one of which is enough; whether a recent password confirmation is needed).
EXPECTED: dict[str, tuple[tuple[str, ...], bool]] = {
    "GET /api/v1/organization": (("admin.organization.manage",), False),
    "PATCH /api/v1/organization": (("admin.organization.manage",), False),
    "GET /api/v1/departments": (("admin.departments.manage", "admin.teams.manage"), False),
    "POST /api/v1/departments": (("admin.departments.manage",), False),
    "PATCH /api/v1/departments/{department_id}": (("admin.departments.manage",), False),
    "GET /api/v1/teams": (("admin.teams.manage", "admin.users.manage"), False),
    "POST /api/v1/teams": (("admin.teams.manage",), False),
    "PATCH /api/v1/teams/{team_id}": (("admin.teams.manage",), False),
    "GET /api/v1/teams/{team_id}/members": (("admin.teams.manage",), False),
    "PUT /api/v1/teams/{team_id}/members/{user_id}": (("admin.teams.manage",), False),
    "DELETE /api/v1/teams/{team_id}/members/{user_id}": (("admin.teams.manage",), False),
    "GET /api/v1/users": (("admin.users.manage", "admin.teams.manage"), False),
    "POST /api/v1/users": (("admin.users.manage",), True),
    "GET /api/v1/users/{user_id}": (("admin.users.manage",), False),
    "PATCH /api/v1/users/{user_id}": (("admin.users.manage",), False),
    "PUT /api/v1/users/{user_id}/roles": (("admin.users.manage",), True),
    "POST /api/v1/users/{user_id}/disable": (("admin.users.manage",), True),
    "POST /api/v1/users/{user_id}/enable": (("admin.users.manage",), True),
    "POST /api/v1/users/{user_id}/invitation": (("admin.users.manage",), True),
    "DELETE /api/v1/users/{user_id}": (("admin.users.manage",), True),
}


def test_every_guard_is_the_one_written_down() -> None:
    actual = {
        route_id(route): (route.requirement.permissions, route.requirement.step_up)
        for route in GUARDED
        if route.requirement is not None
    }
    assert actual == EXPECTED


def test_every_route_is_guarded_or_listed_as_unguarded() -> None:
    unclassified = [
        route_id(route)
        for route in ROUTES
        if (route.requirement is None) == (route_id(route) not in UNGUARDED)
    ]
    assert unclassified == [], "guard these routes, or list them in UNGUARDED with a reason"
    stale = set(UNGUARDED) - {route_id(route) for route in ROUTES}
    assert stale == set(), "UNGUARDED lists routes that no longer exist"


@dataclass(frozen=True)
class Caller:
    role: str
    token: str
    csrf: str


@pytest.fixture
async def callers(
    app_db: Database, valkey: Redis, make_organization, make_user
) -> AsyncIterator[tuple[FastAPI, list[Caller]]]:
    """An app, and a stepped-up session for each role (so step-up never hides a 403)."""
    app = create_app(SETTINGS, db=app_db, redis=valkey, identity=IDENTITY)
    acme = await make_organization("Acme")
    callers: list[Caller] = []
    now = datetime.now(UTC)
    for role in ROLES:
        organization = PLATFORM_ORGANIZATION_ID if role == "super_admin" else acme
        user = await make_user(organization, roles=[role])
        async with app_db.tenant(organization) as session:
            token, csrf, row = await create_session(
                session,
                user_id=user,
                organization_id=organization,
                ip=None,
                user_agent=None,
                settings=IDENTITY,
                now=now,
            )
            row.stepped_up_at = now
        callers.append(Caller(role, token, csrf))
    yield app, callers


def concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", lambda _: str(uuid7()), path)


async def call(app: FastAPI, route: ApiRoute, caller: Caller | None) -> tuple[int, str | None]:
    headers = {"Origin": ORIGIN, "Idempotency-Key": f"matrix-{uuid7()}"}
    cookies: dict[str, str] = {}
    if caller is not None:
        headers["X-CSRF-Token"] = caller.csrf
        cookies = {SESSION_COOKIE: caller.token, CSRF_COOKIE: caller.csrf}
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url=ORIGIN,
        headers=headers,
        cookies=cookies,
    ) as client:
        body = {"json": {}} if route.method in {"POST", "PUT", "PATCH"} else {}
        answer = await client.request(route.method, concrete(route.path), **body)
    code = answer.json().get("code") if answer.content and answer.status_code >= 400 else None
    return answer.status_code, code


@pytest.mark.db
@pytest.mark.parametrize("route", GUARDED, ids=route_id)
async def test_every_guarded_route_for_every_role(
    route: ApiRoute, callers: tuple[FastAPI, list[Caller]]
) -> None:
    app, people = callers
    assert route.requirement is not None
    wrong: list[str] = []
    for caller in people:
        allowed = any(p in permissions_for([caller.role]) for p in route.requirement.permissions)
        status, code = await call(app, route, caller)
        refused = status == 403 and code == "forbidden"
        if allowed == refused:
            wrong.append(f"{caller.role}: {status} {code} (allowed={allowed})")
    assert wrong == []


@pytest.mark.db
@pytest.mark.parametrize("route", GUARDED, ids=route_id)
async def test_every_guarded_route_needs_a_session(
    route: ApiRoute, callers: tuple[FastAPI, list[Caller]]
) -> None:
    app, _ = callers
    assert await call(app, route, None) == (401, "unauthenticated")
