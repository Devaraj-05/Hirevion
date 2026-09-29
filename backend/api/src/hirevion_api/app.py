"""`create_app()`: the API with its middleware, error handling, routes and resources."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from importlib.metadata import version

from fastapi import FastAPI
from redis.asyncio import Redis
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from hirevion_api import health
from hirevion_api.idempotency import install_idempotency_handler
from hirevion_api.middleware import (
    BodySizeLimitMiddleware,
    HostCheckMiddleware,
    SecurityHeadersMiddleware,
    UnhandledErrorMiddleware,
)
from hirevion_api.problems import install_problem_handlers
from hirevion_api.routing import API_PREFIX, build_openapi, operation_id
from hirevion_api.settings import ApiSettings, load_api_settings
from hirevion_core.db.session import Database, create_database
from hirevion_core.settings import CoreSettings, load_core_settings


def create_app(
    api: ApiSettings | None = None,
    *,
    core: CoreSettings | None = None,
    db: Database | None = None,
    redis: Redis | None = None,
) -> FastAPI:
    """Build the API. Injected `db` and `redis` are used as they are and never closed here;
    otherwise the lifespan opens them from `core` (loaded from `.env` when not given)."""
    settings = api or load_api_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            if app.state.db is None or app.state.redis is None:
                resolved = core or load_core_settings()
                if app.state.db is None:
                    app.state.db = create_database(resolved, "app")
                    stack.push_async_callback(app.state.db.dispose)
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

    # Starlette runs the last-added middleware first: proxy headers, then the host check,
    # then the body limit, security headers and the catch-all for unhandled errors.
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)
    app.add_middleware(HostCheckMiddleware, allowed_hosts=settings.hosts)
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=settings.proxies)
    return app
