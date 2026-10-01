"""Access refusals reach clients as RFC 9457 problems, with field errors for forms."""

from collections.abc import Callable

from fastapi import APIRouter, FastAPI
from httpx import AsyncClient

from hirevion_api.access.errors import install_access_handlers
from hirevion_api.problems import PROBLEM_MEDIA_TYPE, install_problem_handlers
from hirevion_core.access.errors import Conflict, Refused

router = APIRouter(prefix="/api/v1/test")


@router.post("/departments")
async def create_department() -> None:
    raise Conflict("name-taken", "That name is already in use", field="name")


@router.post("/escalate")
async def escalate() -> None:
    raise Refused("escalation", "You can't grant permissions you don't hold", detail="jobs.create")


def app() -> FastAPI:
    application = FastAPI()
    install_problem_handlers(application)
    install_access_handlers(application)
    application.include_router(router)
    return application


async def test_a_field_refusal_points_at_the_field(
    client_for: Callable[[FastAPI], AsyncClient],
) -> None:
    answer = await client_for(app()).post("/api/v1/test/departments")
    assert answer.status_code == 409
    assert answer.headers["content-type"] == PROBLEM_MEDIA_TYPE
    body = answer.json()
    assert (body["code"], body["title"]) == ("name-taken", "That name is already in use")
    assert body["errors"] == [{"detail": "That name is already in use", "pointer": "#/name"}]
    assert body["instance"] == "/api/v1/test/departments"


async def test_a_refusal_without_a_field_has_no_field_errors(
    client_for: Callable[[FastAPI], AsyncClient],
) -> None:
    answer = await client_for(app()).post("/api/v1/test/escalate")
    assert answer.status_code == 403
    body = answer.json()
    assert (body["code"], body["detail"]) == ("escalation", "jobs.create")
    assert "errors" not in body
