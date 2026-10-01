"""Route guards: permission first, then step-up (plan Task 4, ADR-0014)."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated

import pytest
from fastapi import APIRouter, FastAPI
from httpx import AsyncClient

from hirevion_api.authz import (
    Principal,
    Requires,
    api_routes,
    current_principal,
    requires,
)
from hirevion_api.problems import install_problem_handlers
from hirevion_core.identity.sessions import SessionContext
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.ids import uuid7

router = APIRouter(prefix="/api/v1/test")


@router.post("/sensitive")
async def sensitive(
    principal: Annotated[Principal, requires("admin.users.manage", step_up=True)],
) -> dict[str, str]:
    return {"user": str(principal.user_id)}


@router.get("/either")
async def either(
    principal: Annotated[Principal, requires("admin.users.manage", "admin.teams.manage")],
) -> dict[str, bool]:
    return {"ok": True}


@router.get("/open")
async def open_route() -> dict[str, bool]:
    return {"ok": True}


def principal(*permissions: str, stepped_up_at: datetime | None = None) -> Principal:
    context = SessionContext(uuid7(), uuid7(), uuid7(), b"csrf", stepped_up_at)
    return Principal(context, frozenset(permissions), frozenset())


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.state.identity = IdentitySettings()
    install_problem_handlers(app)
    app.include_router(router)
    return app


@pytest.fixture
def as_principal(
    app: FastAPI, client_for: Callable[[FastAPI], AsyncClient]
) -> Callable[[Principal], AsyncClient]:
    def make(who: Principal) -> AsyncClient:
        async def override() -> Principal:
            return who

        app.dependency_overrides[current_principal] = override
        return client_for(app)

    return make


def test_a_guard_names_known_permissions() -> None:
    with pytest.raises(ValueError, match=r"no\.such"):
        Requires("no.such")
    with pytest.raises(ValueError, match="at least one"):
        Requires()


async def test_a_missing_permission_is_refused_before_step_up_is_considered(
    as_principal: Callable[[Principal], AsyncClient],
) -> None:
    client = as_principal(principal("jobs.view"))
    answer = await client.post("/api/v1/test/sensitive")
    assert answer.status_code == 403
    assert answer.json()["code"] == "forbidden"


async def test_a_permitted_user_must_step_up_first(
    as_principal: Callable[[Principal], AsyncClient],
) -> None:
    stale = datetime.now(UTC) - timedelta(minutes=11)
    client = as_principal(principal("admin.users.manage", stepped_up_at=stale))
    answer = await client.post("/api/v1/test/sensitive")
    assert answer.status_code == 403
    assert answer.json()["code"] == "step-up-required"
    assert answer.json()["max_age_seconds"] == 600


async def test_a_permitted_and_stepped_up_user_gets_through(
    as_principal: Callable[[Principal], AsyncClient],
) -> None:
    who = principal("admin.users.manage", stepped_up_at=datetime.now(UTC))
    answer = await as_principal(who).post("/api/v1/test/sensitive")
    assert answer.status_code == 200
    assert answer.json() == {"user": str(who.user_id)}


@pytest.mark.parametrize("permission", ["admin.users.manage", "admin.teams.manage"])
async def test_any_one_of_several_permissions_is_enough(
    as_principal: Callable[[Principal], AsyncClient], permission: str
) -> None:
    answer = await as_principal(principal(permission)).get("/api/v1/test/either")
    assert answer.status_code == 200


def test_routes_are_listed_with_their_guards(app: FastAPI) -> None:
    routes = {(route.method, route.path): route.requirement for route in api_routes(app)}
    sensitive_guard = routes[("POST", "/api/v1/test/sensitive")]
    assert sensitive_guard is not None
    assert sensitive_guard.permissions == ("admin.users.manage",)
    assert sensitive_guard.step_up is True
    either_guard = routes[("GET", "/api/v1/test/either")]
    assert either_guard is not None
    assert either_guard.permissions == ("admin.users.manage", "admin.teams.manage")
    assert routes[("GET", "/api/v1/test/open")] is None
