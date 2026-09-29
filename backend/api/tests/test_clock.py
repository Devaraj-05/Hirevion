"""Clock sync: clients line their event times up with the server's (master plan §3.2)."""

import time
from collections.abc import Callable

from fastapi import FastAPI
from httpx import AsyncClient

from hirevion_api.app import create_app
from hirevion_api.settings import ApiSettings


async def test_the_server_reports_when_it_received_and_answered(
    client_for: Callable[[FastAPI], AsyncClient],
) -> None:
    before = time.time() * 1000
    response = await client_for(create_app(ApiSettings())).get("/api/v1/time")
    after = time.time() * 1000

    body = response.json()
    assert response.status_code == 200
    assert set(body) == {"received_at_ms", "sent_at_ms"}
    assert before - 1 <= body["received_at_ms"] <= body["sent_at_ms"] <= after + 1
    assert response.headers["cache-control"] == "no-store"
