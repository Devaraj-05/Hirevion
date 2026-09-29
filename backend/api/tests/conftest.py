"""API test helpers. The database fixtures come from `backend/conftest.py`."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

BASE_URL = "http://api.hirevion.localhost"


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
