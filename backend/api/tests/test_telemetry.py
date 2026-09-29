"""Requests are traced, and problem bodies point at their trace."""

from collections.abc import Callable, Iterator
from typing import Annotated

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import AsyncClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind
from redis.asyncio import Redis
from sqlalchemy import text

from hirevion_api.app import create_app
from hirevion_api.deps import get_db
from hirevion_api.settings import ApiSettings
from hirevion_core.db.session import Database
from hirevion_core.telemetry import Telemetry, TelemetrySettings, setup_telemetry

router = APIRouter(prefix="/api/v1/test")


@router.get("/boom")
async def boom() -> None:
    raise RuntimeError("boom")


@router.get("/query")
async def query(db: Annotated[Database, Depends(get_db)]) -> dict[str, int]:
    async with db.unscoped() as session:
        value = await session.scalar(text("SELECT length(:secret)"), {"secret": "hunter2"})
    return {"length": int(value or 0)}


@pytest.fixture
def exporter() -> InMemorySpanExporter:
    return InMemorySpanExporter()


@pytest.fixture
def telemetry(exporter: InMemorySpanExporter) -> Iterator[Telemetry]:
    telemetry = setup_telemetry(
        "hirevion-api-test",
        settings=TelemetrySettings(),
        span_exporter=exporter,
        metrics=False,
        logs=False,
        set_global=False,
    )
    yield telemetry
    telemetry.shutdown()


def server_spans(exporter: InMemorySpanExporter) -> list[object]:
    return [span for span in exporter.get_finished_spans() if span.kind == SpanKind.SERVER]


async def test_requests_are_traced_and_problems_name_their_trace(
    telemetry: Telemetry,
    exporter: InMemorySpanExporter,
    client_for: Callable[[FastAPI], AsyncClient],
) -> None:
    app = create_app(ApiSettings(), telemetry=telemetry)
    app.include_router(router)
    client = client_for(app)

    await client.get("/api/v1/health/live")
    assert server_spans(exporter) == []  # health probes are not traced

    response = await client.get("/api/v1/test/boom")
    [span] = [s for s in exporter.get_finished_spans() if s.kind == SpanKind.SERVER]
    assert span.attributes is not None
    assert span.attributes["http.route"] == "/api/v1/test/boom"
    assert response.status_code == 500
    assert response.json()["trace_id"] == format(span.context.trace_id, "032x")


@pytest.mark.db
async def test_queries_are_traced_without_their_values(
    app_db: Database,
    telemetry: Telemetry,
    exporter: InMemorySpanExporter,
    client_for: Callable[[FastAPI], AsyncClient],
) -> None:
    app = create_app(ApiSettings(), db=app_db, telemetry=telemetry)
    app.include_router(router)
    response = await client_for(app).get("/api/v1/test/query")
    assert response.json() == {"length": 7}

    spans = exporter.get_finished_spans()
    queries = [span for span in spans if span.kind == SpanKind.CLIENT and span.attributes]
    assert queries, [span.name for span in spans]
    assert all("hunter2" not in str(dict(span.attributes or {})) for span in spans)


@pytest.mark.db
async def test_readiness_probes_leave_no_spans(
    app_db: Database,
    valkey: Redis,
    telemetry: Telemetry,
    exporter: InMemorySpanExporter,
    client_for: Callable[[FastAPI], AsyncClient],
) -> None:
    app = create_app(ApiSettings(), db=app_db, redis=valkey, telemetry=telemetry)
    response = await client_for(app).get("/api/v1/health/ready")
    assert response.status_code == 200
    assert exporter.get_finished_spans() == ()


def test_telemetry_settings_are_read_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
    monkeypatch.setenv("HV_ENVIRONMENT", "staging")
    settings = TelemetrySettings()
    assert settings.otel_sdk_disabled is True
    assert settings.otel_exporter_otlp_endpoint == "http://collector:4318"
    assert settings.hv_environment == "staging"
