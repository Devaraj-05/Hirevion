"""Liveness and readiness probes (master plan §5.4)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

from fastapi import Depends
from opentelemetry.instrumentation.utils import suppress_instrumentation
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text

from hirevion_api.deps import get_db, get_redis
from hirevion_api.problems import ProblemError
from hirevion_api.routing import api_router
from hirevion_core.db.session import Database

log = logging.getLogger(__name__)

router = api_router(tags=["health"])
CHECK_TIMEOUT_SECONDS = 2


class Liveness(BaseModel):
    status: Literal["ok"] = "ok"


class Readiness(BaseModel):
    status: Literal["ok"]
    checks: dict[str, str]


@router.get("/health/live")
async def get_liveness() -> Liveness:
    """The process is up. It checks nothing else, so a restart can't fix what it reports."""
    return Liveness()


@router.get("/health/ready")
async def get_readiness(
    db: Annotated[Database, Depends(get_db)], redis: Annotated[Redis, Depends(get_redis)]
) -> Readiness:
    """PostgreSQL and Valkey answer; 503 `service-unavailable` names what doesn't."""

    async def database() -> None:
        async with db.unscoped() as session:
            await session.execute(text("SELECT 1"))

    async def valkey() -> None:
        await redis.ping()

    # Probes run every few seconds; tracing them would bury real traffic in orphan spans.
    with suppress_instrumentation():
        checks = {
            "database": await _check("database", database),
            "valkey": await _check("valkey", valkey),
        }
    if any(state != "ok" for state in checks.values()):
        raise ProblemError(
            503,
            "service-unavailable",
            "Service unavailable",
            "A service this API depends on is not reachable.",
            checks=checks,
        )
    return Readiness(status="ok", checks=checks)


async def _check(name: str, probe: Callable[[], Awaitable[None]]) -> str:
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
            await probe()
    except Exception:
        log.warning("Readiness check %s failed", name, exc_info=True)
        return "unavailable"
    return "ok"
