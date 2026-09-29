"""`create_app()`: the API with its middleware, error handling, routes and resources."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from importlib.metadata import version

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from redis.asyncio import Redis
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from hirevion_api import clock, health
from hirevion_api.idempotency import install_idempotency_handler
from hirevion_api.middleware import (
    BodySizeLimitMiddleware,
    HostCheckMiddleware,
    SecurityHeadersMiddleware,
    UnhandledErrorMiddleware,
)
from hirevion_api.problems import install_problem_handlers
from hirevion_api.ratelimit import RateLimitMiddleware
from hirevion_api.routing import API_PREFIX, build_openapi, operation_id
from hirevion_api.settings import ApiSettings, load_api_settings
from hirevion_core.db.session import Database, create_database
from hirevion_core.ratelimit import RateRule
from hirevion_core.settings import CoreSettings, load_core_settings
from hirevion_core.telemetry import Telemetry, instrument_engine


def create_app(
    api: ApiSettings | None = None,
    *,
    core: CoreSettings | None = None,
    db: Database | None = None,
    redis: Redis | None = None,
    telemetry: Telemetry | None = None,
) -> FastAPI:
    """Build the API. Injected `db` and `redis` are used as they are and never closed here;
    otherwise the lifespan opens them from `core` (loaded from `.env` when not given).
    `telemetry` traces requests and queries; the lifespan shuts it down on exit."""
    settings = api or load_api_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            if telemetry is not None:
                stack.callback(telemetry.shutdown)
            if app.state.db is None or app.state.redis is None:
                resolved = core or load_core_settings()
                if app.state.db is None:
                    app.state.db = create_database(resolved, "app")
                    stack.push_async_callback(app.state.db.dispose)
                    if telemetry is not None:
                        instrument_engine(app.state.db.engine, telemetry)
                if app.state.redis is None:
                    app.state.redis = Redis.from_url(resolved.valkey_url())
                    stack.push_async_callback(app.state.redis.aclose)
            yield

    docs = settings.docs_enabled
    app = FastAPI(
        title="Hirevion API",
        version=version("hirevion-api"),
        lifespan=lifespan,
        openapi_url=f"{API_PREFIX}/openapi.json" if docs else None,
        docs_url=f"{API_PREFIX}/docs" if docs else None,
        redoc_url=None,
        generate_unique_id_function=operation_id,
    )
    app.state.db = db
    app.state.redis = redis
    app.openapi = lambda: build_openapi(app)  # type: ignore[method-assign]

    install_problem_handlers(app)
    install_idempotency_handler(app)
    app.include_router(health.router)
    app.include_router(clock.router)
    if telemetry is not None and telemetry.enabled:
        FastAPIInstrumentor.instrument_app(
            app,
            tracer_provider=telemetry.tracer_provider,
            meter_provider=telemetry.meter_provider,
            excluded_urls=f"{API_PREFIX}/health/",
        )
        if db is not None:
            instrument_engine(db.engine, telemetry)

    # Starlette runs the last-added middleware first: proxy headers, the host check, the
    # per-IP rate limit, the body limit, security headers, then the catch-all for errors.
    ip_rule = RateRule("ip", settings.ip_rate_limit, settings.ip_rate_window_seconds)
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)
    app.add_middleware(RateLimitMiddleware, rule=ip_rule)
    app.add_middleware(HostCheckMiddleware, allowed_hosts=settings.hosts)
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=settings.proxies)
    return app
