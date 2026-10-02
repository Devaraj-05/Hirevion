"""`create_app()`: the API with its middleware, error handling, routes and resources."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from importlib.metadata import version

import aiohttp
from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from redis.asyncio import Redis
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from hirevion_api import clock, health
from hirevion_api.access.errors import install_access_handlers
from hirevion_api.access.organization import router as organization_router
from hirevion_api.access.structure import router as structure_router
from hirevion_api.access.users import router as users_router
from hirevion_api.auth.csrf import CsrfMiddleware
from hirevion_api.auth.router import router as auth_router
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
from hirevion_core.identity.breach import (
    CompositeChecker,
    HibpChecker,
    LocalListChecker,
    aiohttp_range_fetcher,
)
from hirevion_core.identity.passwords import PasswordPolicy
from hirevion_core.identity.settings import IdentitySettings, load_identity_settings
from hirevion_core.mail.runner import run_workers
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
    identity: IdentitySettings | None = None,
) -> FastAPI:
    """Build the API. Injected `db` and `redis` are used as they are and never closed here;
    otherwise the lifespan opens them from `core` (loaded from `.env` when not given), and also
    runs the background workers (`HV_API_RUN_WORKERS`). `telemetry` traces requests and
    queries; the lifespan shuts it down on exit."""
    settings = api or load_api_settings()
    identity_settings = identity or load_identity_settings()
    local_passwords = LocalListChecker.from_package()

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
                if settings.run_workers:
                    stop = asyncio.Event()
                    workers = asyncio.create_task(run_workers(resolved, stop))
                    stack.push_async_callback(_stop_workers, stop, workers)
            if identity_settings.hibp_enabled:
                session = aiohttp.ClientSession()
                stack.push_async_callback(session.close)
                breaches = CompositeChecker(
                    local_passwords, HibpChecker(aiohttp_range_fetcher(session))
                )
                app.state.password_policy = PasswordPolicy(breaches)
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
    app.state.identity = identity_settings
    # The bundled list always applies; the lifespan adds Have I Been Pwned when enabled.
    app.state.password_policy = PasswordPolicy(CompositeChecker(local_passwords))
    app.openapi = lambda: build_openapi(app)  # type: ignore[method-assign]

    install_problem_handlers(app)
    install_access_handlers(app)
    install_idempotency_handler(app)
    app.include_router(health.router)
    app.include_router(clock.router)
    app.include_router(auth_router)
    app.include_router(organization_router)
    app.include_router(structure_router)
    app.include_router(users_router)
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
    # per-IP rate limit, the body limit, security headers, the catch-all for errors, then CSRF.
    ip_rule = RateRule("ip", settings.ip_rate_limit, settings.ip_rate_window_seconds)
    app.add_middleware(CsrfMiddleware, allowed_origins=settings.origins)
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)
    app.add_middleware(RateLimitMiddleware, rule=ip_rule)
    app.add_middleware(HostCheckMiddleware, allowed_hosts=settings.hosts)
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=settings.proxies)
    return app


async def _stop_workers(stop: asyncio.Event, workers: asyncio.Task[None]) -> None:
    stop.set()
    with suppress(TimeoutError):
        await asyncio.wait_for(workers, timeout=10)
