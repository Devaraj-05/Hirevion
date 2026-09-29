"""Rate limits over HTTP: 429 problems and the RateLimit headers."""

import logging
from collections.abc import AsyncIterator, Callable

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import AsyncClient
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff

from hirevion_api.app import create_app
from hirevion_api.ratelimit import rate_limited
from hirevion_api.settings import ApiSettings
from hirevion_core.ratelimit import RateRule

router = APIRouter(prefix="/api/v1/test")


@router.get("/ping")
async def ping() -> dict[str, bool]:
    return {"ok": True}


@router.post("/login", dependencies=[Depends(rate_limited(RateRule("login", 1, 60)))])
async def login() -> dict[str, bool]:
    return {"ok": True}


@router.post(
    "/strict", dependencies=[Depends(rate_limited(RateRule("strict", 5, 60, fail_closed=True)))]
)
async def strict() -> dict[str, bool]:
    return {"ok": True}


def client_with(
    client_for: Callable[[FastAPI], AsyncClient], redis: Redis, **settings: object
) -> AsyncClient:
    app = create_app(ApiSettings(**settings), redis=redis)  # type: ignore[arg-type]
    app.include_router(router)
    return client_for(app)


@pytest.fixture
async def unreachable() -> AsyncIterator[Redis]:
    client = Redis(
        host="127.0.0.1", port=1, socket_connect_timeout=0.5, retry=Retry(NoBackoff(), 0)
    )
    yield client
    await client.aclose()


@pytest.mark.db
async def test_the_ip_limit_answers_429_with_headers(
    valkey: Redis, client_for: Callable[[FastAPI], AsyncClient]
) -> None:
    client = client_with(client_for, valkey, ip_rate_limit=2)
    first, second, third = [await client.get("/api/v1/test/ping") for _ in range(3)]
    assert [first.status_code, second.status_code, third.status_code] == [200, 200, 429]
    assert first.headers["ratelimit-policy"] == '"ip";q=2;w=60'
    assert first.headers["ratelimit"] == '"ip";r=1;t=30'
    assert second.headers["ratelimit"] == '"ip";r=0;t=60'
    assert third.json()["code"] == "rate-limited"
    assert 1 <= int(third.headers["retry-after"]) <= 30

    elsewhere = await client.get("/api/v1/test/ping", headers={"x-forwarded-for": "198.51.100.7"})
    assert elsewhere.status_code == 200


@pytest.mark.db
async def test_health_checks_are_never_limited(
    valkey: Redis, client_for: Callable[[FastAPI], AsyncClient]
) -> None:
    client = client_with(client_for, valkey, ip_rate_limit=1)
    responses = [await client.get("/api/v1/health/live") for _ in range(3)]
    assert [response.status_code for response in responses] == [200, 200, 200]
    assert "ratelimit" not in responses[0].headers


@pytest.mark.db
async def test_a_route_rule_adds_its_own_limit(
    valkey: Redis, client_for: Callable[[FastAPI], AsyncClient]
) -> None:
    client = client_with(client_for, valkey)
    first = await client.post("/api/v1/test/login")
    second = await client.post("/api/v1/test/login")
    assert first.status_code == 200
    assert first.headers["ratelimit-policy"] == '"ip";q=600;w=60, "login";q=1;w=60'
    assert second.status_code == 429
    assert second.json()["code"] == "rate-limited"
    assert '"login";q=1;w=60' in second.headers["ratelimit-policy"]


async def test_the_global_limit_fails_open(
    unreachable: Redis,
    client_for: Callable[[FastAPI], AsyncClient],
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = client_with(client_for, unreachable, ip_rate_limit=1)
    with caplog.at_level(logging.WARNING):
        responses = [await client.get("/api/v1/test/ping") for _ in range(2)]
    assert [response.status_code for response in responses] == [200, 200]
    assert "rate limit" in caplog.text.lower()


async def test_a_fail_closed_rule_refuses_without_valkey(
    unreachable: Redis, client_for: Callable[[FastAPI], AsyncClient]
) -> None:
    response = await client_with(client_for, unreachable).post("/api/v1/test/strict")
    assert response.status_code == 503
    assert response.json()["code"] == "service-unavailable"
