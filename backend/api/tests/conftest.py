"""API test helpers. The database fixtures come from `backend/conftest.py`."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Request
from redis.asyncio import Redis

from hirevion_api.app import create_app
from hirevion_api.auth.cookies import CSRF_COOKIE, SESSION_COOKIE
from hirevion_api.settings import ApiSettings
from hirevion_core.db.session import Database
from hirevion_core.identity.sessions import create_session
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.ids import uuid7

BASE_URL = "http://api.hirevion.localhost"
# The recruiter app's origin: session cookies are Secure, and state changes need this Origin.
ORIGIN = "https://app.hirevion.localhost"
IDENTITY = IdentitySettings(hibp_enabled=False, web_origin=ORIGIN)


@pytest.fixture
async def client_for() -> AsyncIterator[Callable[[FastAPI], AsyncClient]]:
    """Makes HTTP clients for an app; unhandled errors come back as responses, as in production."""
    clients: list[AsyncClient] = []

    def make(app: FastAPI) -> AsyncClient:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        client = AsyncClient(transport=transport, base_url=BASE_URL)
        clients.append(client)
        return client

    yield make
    for client in clients:
        await client.aclose()


@pytest.fixture
def api(app_db: Database, valkey: Redis) -> FastAPI:
    """The whole API on the test database, without background workers."""
    return create_app(
        ApiSettings(allowed_origins=ORIGIN, run_workers=False, ip_rate_limit=100_000),
        db=app_db,
        redis=valkey,
        identity=IDENTITY,
    )


class SignedIn(Protocol):
    def __call__(
        self, organization_id: UUID, user_id: UUID, *, stepped_up: bool = True
    ) -> Awaitable[AsyncClient]: ...


@pytest.fixture
async def signed_in(api: FastAPI, app_db: Database) -> AsyncIterator[SignedIn]:
    """Makes a browser-like client already signed in as a user (a session made directly, so
    tests don't spend sign-in's rate limits), stepped up unless asked otherwise. It sends the
    app's Origin, the CSRF header and a fresh Idempotency-Key on every request."""
    clients: list[AsyncClient] = []

    async def make(organization_id: UUID, user_id: UUID, *, stepped_up: bool = True) -> AsyncClient:
        now = datetime.now(UTC)
        async with app_db.tenant(organization_id) as session:
            token, csrf, row = await create_session(
                session,
                user_id=user_id,
                organization_id=organization_id,
                ip=None,
                user_agent="Test browser",
                settings=IDENTITY,
                now=now,
            )
            row.stepped_up_at = now if stepped_up else now - timedelta(hours=1)

        async def fresh_key(request: Request) -> None:
            request.headers.setdefault("Idempotency-Key", f"test-{uuid7()}")

        client = AsyncClient(
            transport=ASGITransport(app=api, raise_app_exceptions=False),
            base_url=ORIGIN,
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
            cookies={SESSION_COOKIE: token, CSRF_COOKIE: csrf},
            event_hooks={"request": [fresh_key]},
        )
        clients.append(client)
        return client

    yield make
    for client in clients:
        await client.aclose()
