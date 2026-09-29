"""Every error is an RFC 9457 problem (master plan §13)."""

import logging
from collections.abc import Callable
from typing import Annotated

import pytest
from fastapi import APIRouter, FastAPI, Header, Query
from httpx import AsyncClient
from pydantic import BaseModel, Field

from hirevion_api.app import create_app
from hirevion_api.problems import PROBLEM_MEDIA_TYPE, ProblemError
from hirevion_api.settings import ApiSettings

router = APIRouter(prefix="/api/v1/test")


class Signup(BaseModel):
    email: str = Field(pattern=r".+@.+")


@router.post("/signup")
async def signup(
    body: Signup,
    limit: Annotated[int, Query(ge=1)] = 1,
    x_token: Annotated[str | None, Header(max_length=3)] = None,
) -> dict[str, bool]:
    return {"ok": True}


@router.get("/conflict")
async def conflict() -> None:
    raise ProblemError(409, "conflict-example", "Conflict", detail="x", thing=1)


@router.get("/boom")
async def boom() -> None:
    raise RuntimeError("the database password is hunter2")


@pytest.fixture
def client(client_for: Callable[[FastAPI], AsyncClient]) -> AsyncClient:
    app = create_app(ApiSettings())
    app.include_router(router)
    return client_for(app)


async def test_a_problem_error_becomes_problem_json(client: AsyncClient) -> None:
    response = await client.get("/api/v1/test/conflict")
    assert response.status_code == 409
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert response.json() == {
        "type": "urn:hirevion:problem:conflict-example",
        "title": "Conflict",
        "status": 409,
        "detail": "x",
        "instance": "/api/v1/test/conflict",
        "code": "conflict-example",
        "trace_id": None,
        "thing": 1,
    }


async def test_body_errors_point_at_the_field(client: AsyncClient) -> None:
    response = await client.post("/api/v1/test/signup", json={"email": "nope"})
    body = response.json()
    assert response.status_code == 422
    assert body["code"] == "validation-failed"
    assert [error["pointer"] for error in body["errors"]] == ["#/email"]
    assert all(error["detail"] for error in body["errors"])


async def test_parameter_and_header_errors_name_them(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/test/signup?limit=0", json={"email": "a@b.c"}, headers={"x-token": "toolong"}
    )
    errors = response.json()["errors"]
    assert response.status_code == 422
    assert {"parameter": "limit"}.items() <= errors[0].items()
    assert {"header": "x-token"}.items() <= errors[1].items()


async def test_a_missing_body_points_at_the_document(client: AsyncClient) -> None:
    response = await client.post("/api/v1/test/signup")
    assert [error["pointer"] for error in response.json()["errors"]] == ["#"]


async def test_unknown_paths_and_wrong_methods(client: AsyncClient) -> None:
    missing = await client.get("/api/v1/nothing-here")
    assert missing.status_code == 404
    assert missing.json()["code"] == "not-found"

    wrong = await client.delete("/api/v1/test/conflict")
    assert wrong.status_code == 405
    assert wrong.json()["code"] == "method-not-allowed"
    assert wrong.headers["allow"] == "GET"


async def test_unhandled_errors_hide_their_details(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR):
        response = await client.get("/api/v1/test/boom")
    assert response.status_code == 500
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert response.json()["code"] == "internal-error"
    assert "hunter2" not in response.text
    assert "RuntimeError" not in response.text
    assert any(record.exc_info for record in caplog.records)


def test_operations_document_problem_responses() -> None:
    spec = create_app(ApiSettings()).openapi()
    operation = spec["paths"]["/api/v1/health/live"]["get"]
    assert operation["operationId"] == "get_liveness"
    problem = {PROBLEM_MEDIA_TYPE: {"schema": {"$ref": "#/components/schemas/Problem"}}}
    assert operation["responses"]["4XX"]["content"] == problem
    assert operation["responses"]["5XX"]["content"] == problem
    assert "Problem" in spec["components"]["schemas"]
