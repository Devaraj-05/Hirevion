"""`create_app()`: the API with its middleware, error handling, routes and resources."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from importlib.metadata import version

import aiohttp
from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from redis.asyncio import Redis
from starlette.types import ASGIApp
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from hirevion_api import clock, dashboard, health
from hirevion_api.access.errors import install_access_handlers
from hirevion_api.access.organization import router as organization_router
from hirevion_api.access.platform import router as platform_router
from hirevion_api.access.roles import router as roles_router
from hirevion_api.access.structure import router as structure_router
from hirevion_api.access.users import router as users_router
from hirevion_api.auth.csrf import CsrfMiddleware
from hirevion_api.auth.router import router as auth_router
from hirevion_api.candidate360.routes import router as candidate360_router
from hirevion_api.candidate_auth.routes import router as candidate_auth_router
from hirevion_api.candidates.routes import router as candidates_router
from hirevion_api.desktop_admin import router as desktop_admin_router
from hirevion_api.evaluation.routes import router as evaluation_router
from hirevion_api.idempotency import install_idempotency_handler
from hirevion_api.interview_session.live import router as interview_live_router
from hirevion_api.interview_session.recruiter import router as interview_recruiter_router
from hirevion_api.interview_session.routes import router as interview_session_router
from hirevion_api.interview_session.webhook import router as livekit_webhook_router
from hirevion_api.interviews.assigned import router as assigned_interviews_router
from hirevion_api.interviews.routes import router as interviews_router
from hirevion_api.jobs.routes import router as jobs_router
from hirevion_api.middleware import (
    BodySizeLimitMiddleware,
    HostCheckMiddleware,
    SecurityHeadersMiddleware,
    TraceStateGuard,
    UnhandledErrorMiddleware,
)
from hirevion_api.portal.recruiter import router as candidate_requests_router
from hirevion_api.portal.routes import router as portal_router
from hirevion_api.problems import install_problem_handlers
from hirevion_api.proctoring.live import router as proctoring_live_router
from hirevion_api.proctoring.recruiter import router as proctoring_recruiter_router
from hirevion_api.proctoring.routes import router as proctoring_router
from hirevion_api.ratelimit import RateLimitMiddleware
from hirevion_api.recordings.desktop import router as recordings_desktop_router
from hirevion_api.recordings.recruiter import router as recordings_recruiter_router
from hirevion_api.reports.routes import router as reports_router
from hirevion_api.review.routes import router as review_router
from hirevion_api.routing import API_PREFIX, build_openapi, operation_id
from hirevion_api.screening.routes import router as screening_router
from hirevion_api.settings import ApiSettings, load_api_settings
from hirevion_api.third_eye.routes import router as third_eye_router
from hirevion_core.ai import AiServices, build_ai
from hirevion_core.ai.settings import load_ai_settings
from hirevion_core.candidate_access.tokens import (
    CandidateAuthSettings,
    TokenSigner,
    load_candidate_auth_settings,
)
from hirevion_core.db.session import Database, create_database
from hirevion_core.documents.intake import BlobStore
from hirevion_core.identity.breach import (
    CompositeChecker,
    HibpChecker,
    LocalListChecker,
    aiohttp_range_fetcher,
)
from hirevion_core.identity.passwords import PasswordPolicy
from hirevion_core.identity.settings import IdentitySettings, load_identity_settings
from hirevion_core.interview_session.media import MediaControl, build_media
from hirevion_core.mail.runner import run_workers
from hirevion_core.ratelimit import RateRule
from hirevion_core.reports.pdf import PdfRenderer, PlaywrightPdfRenderer
from hirevion_core.settings import CoreSettings, load_core_settings
from hirevion_core.storage.service import load_optional_storage
from hirevion_core.telemetry import Telemetry, instrument_engine

log = logging.getLogger(__name__)

# Candidates have a second factor in the desktop's device key and new-device code (ADR-0020).
CANDIDATE_PASSWORD_MIN = 12

# Routes that take file uploads, and so a larger body: a description, or a resume or ZIP of them.
DESCRIPTION_UPLOAD = re.compile(rf"{API_PREFIX}/jobs/[^/]+/jd")
RESUME_UPLOAD = re.compile(rf"{API_PREFIX}/jobs/[^/]+/resumes")


def create_app(
    api: ApiSettings | None = None,
    *,
    core: CoreSettings | None = None,
    db: Database | None = None,
    redis: Redis | None = None,
    telemetry: Telemetry | None = None,
    identity: IdentitySettings | None = None,
    storage: BlobStore | None = None,
    ai: AiServices | None = None,
    candidate_auth: CandidateAuthSettings | None = None,
    media: MediaControl | None = None,
    pdf: PdfRenderer | None = None,
) -> FastAPI:
    """Build the API. Injected `db` and `redis` are used as they are and never closed here;
    otherwise the lifespan opens them from `core` (loaded from `.env` when not given), and also
    runs the background workers (`HV_API_RUN_WORKERS`). `telemetry` traces requests and
    queries; the lifespan shuts it down on exit. `ai` is built from `.env` when not given; the
    routes that need it answer 503 when it can't be (missing keys). `media` (LiveKit) likewise:
    the interview routes answer 503 without it."""
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
            if app.state.storage is None:
                app.state.storage = load_optional_storage()
                if app.state.storage is not None:
                    stack.push_async_callback(app.state.storage.aclose)
            if app.state.ai is None:
                try:
                    app.state.ai = build_ai(load_ai_settings(), app.state.db)
                except ValueError:
                    log.exception("AI features are off: the AI services can't start")
                else:
                    stack.push_async_callback(app.state.ai.aclose)
            if app.state.media is None:
                try:
                    app.state.media = build_media()
                except ValueError:
                    log.exception("Interviews can't start: the media settings are invalid")
            if identity_settings.hibp_enabled:
                session = aiohttp.ClientSession()
                stack.push_async_callback(session.close)
                breaches = CompositeChecker(
                    local_passwords, HibpChecker(aiohttp_range_fetcher(session))
                )
                app.state.password_policy = PasswordPolicy(breaches)
                app.state.candidate_password_policy = PasswordPolicy(
                    breaches, min_length=CANDIDATE_PASSWORD_MIN
                )
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
    app.state.storage = storage
    app.state.ai = ai
    app.state.identity = identity_settings
    app.state.media = media
    app.state.pdf_renderer = pdf or PlaywrightPdfRenderer()
    app.state.allowed_origins = settings.origins
    app.state.candidate_auth = candidate_auth or load_candidate_auth_settings()
    app.state.candidate_signer = TokenSigner.from_settings(app.state.candidate_auth)
    # The bundled list always applies; the lifespan adds Have I Been Pwned when enabled.
    app.state.password_policy = PasswordPolicy(CompositeChecker(local_passwords))
    app.state.candidate_password_policy = PasswordPolicy(
        CompositeChecker(local_passwords), min_length=CANDIDATE_PASSWORD_MIN
    )
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
    app.include_router(roles_router)
    app.include_router(platform_router)
    app.include_router(jobs_router)
    app.include_router(candidates_router)
    app.include_router(screening_router)
    app.include_router(interviews_router)
    app.include_router(assigned_interviews_router)
    app.include_router(dashboard.router)
    app.include_router(candidate_auth_router)
    app.include_router(desktop_admin_router)
    app.include_router(interview_session_router)
    app.include_router(interview_recruiter_router)
    app.include_router(evaluation_router)
    app.include_router(livekit_webhook_router)
    app.include_router(interview_live_router)
    app.include_router(recordings_desktop_router)
    app.include_router(recordings_recruiter_router)
    app.include_router(proctoring_router)
    app.include_router(proctoring_recruiter_router)
    app.include_router(proctoring_live_router)
    app.include_router(portal_router)
    app.include_router(candidate_requests_router)
    app.include_router(third_eye_router)
    app.include_router(reports_router)
    app.include_router(review_router)
    app.include_router(candidate360_router)
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
    app.add_middleware(
        CsrfMiddleware, allowed_origins=settings.origins, portal_origins=settings.portal
    )
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        BodySizeLimitMiddleware,
        max_bytes=settings.max_body_bytes,
        upload_limits=[
            (DESCRIPTION_UPLOAD, settings.max_upload_bytes),
            (RESUME_UPLOAD, settings.max_archive_upload_bytes),
        ],
    )
    app.add_middleware(RateLimitMiddleware, rule=ip_rule)
    app.add_middleware(HostCheckMiddleware, allowed_hosts=settings.hosts)
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=settings.proxies)
    _guard_tracestate(app)
    return app


def _guard_tracestate(app: FastAPI) -> None:
    """Puts `TraceStateGuard` outside everything, the tracing middleware included (which
    replaces `build_middleware_stack` to make itself outermost)."""
    build = app.build_middleware_stack

    def build_guarded() -> ASGIApp:
        return TraceStateGuard(build())

    app.build_middleware_stack = build_guarded  # type: ignore[method-assign]


async def _stop_workers(stop: asyncio.Event, workers: asyncio.Task[None]) -> None:
    stop.set()
    with suppress(TimeoutError):
        await asyncio.wait_for(workers, timeout=10)
