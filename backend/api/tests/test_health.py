from collections.abc import Callable

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff

from hirevion_api.app import create_app
from hirevion_api.settings import ApiSettings
from hirevion_core.db.session import Database
from hirevion_core.settings import CoreSettings


async def test_liveness_needs_nothing(client_for: Callable[[FastAPI], AsyncClient]) -> None:
    response = await client_for(create_app(ApiSettings())).get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.db
async def test_readiness_checks_the_database_and_valkey(
    app_db: Database, valkey: Redis, client_for: Callable[[FastAPI], AsyncClient]
) -> None:
    app = create_app(ApiSettings(), db=app_db, redis=valkey)
    response = await client_for(app).get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "valkey": "ok"}}


@pytest.mark.db
async def test_readiness_reports_what_is_down(
    app_db: Database, client_for: Callable[[FastAPI], AsyncClient]
) -> None:
    unreachable = Redis(
        host="127.0.0.1", port=1, socket_connect_timeout=0.5, retry=Retry(NoBackoff(), 0)
    )
    try:
        app = create_app(ApiSettings(), db=app_db, redis=unreachable)
        response = await client_for(app).get("/api/v1/health/ready")
    finally:
        await unreachable.aclose()
    assert response.status_code == 503
    assert response.json()["code"] == "service-unavailable"
    assert response.json()["checks"] == {"database": "ok", "valkey": "unavailable"}


@pytest.mark.db
async def test_the_lifespan_opens_and_closes_its_own_connections(
    core_settings: CoreSettings,
    migrated_database: str,
    client_for: Callable[[FastAPI], AsyncClient],
) -> None:
    settings = core_settings.model_copy(update={"postgres_db": migrated_database})
    app = create_app(ApiSettings(), core=settings)
    async with app.router.lifespan_context(app):
        assert isinstance(app.state.db, Database)
        response = await client_for(app).get("/api/v1/health/ready")
        assert response.status_code == 200
