"""`hv create-super-admin`, `hv seed-identity`, `hv worker` and `hv reset-limits` (SP-02)."""

from __future__ import annotations

import asyncio

from redis.asyncio import Redis

from hirevion_core.db.session import create_database
from hirevion_core.identity.bootstrap import SeedResult, create_super_admin, seed_identity
from hirevion_core.identity.settings import load_identity_settings
from hirevion_core.mail.runner import run_workers
from hirevion_core.ratelimit import reset_limits
from hirevion_core.settings import load_core_settings


async def invite_super_admin(email: str, name: str) -> str:
    db = create_database(load_core_settings(), "app")
    try:
        return await create_super_admin(
            db, email=email, name=name, settings=load_identity_settings()
        )
    finally:
        await db.dispose()


async def seed(password: str, environment: str) -> SeedResult:
    core = load_core_settings()
    admin, db = create_database(core, "admin"), create_database(core, "app")
    try:
        return await seed_identity(admin, db, password=password, environment=environment)
    finally:
        await db.dispose()
        await admin.dispose()


async def work() -> None:
    """Runs until cancelled (Ctrl+C)."""
    await run_workers(load_core_settings(), asyncio.Event())


async def reset_rate_limits() -> int:
    """Clears every rate limit and sign-in lockout in the local Valkey."""
    redis = Redis.from_url(load_core_settings().valkey_url())
    try:
        return await reset_limits(redis)
    finally:
        await redis.aclose()
