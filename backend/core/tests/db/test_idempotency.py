"""The idempotency-key store: a create retried with the same key happens once."""

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.db.session import Database
from hirevion_core.idempotency import (
    IdempotencyInProgress,
    IdempotencyKeyReused,
    StoredResponse,
    claim,
    purge_idempotency_keys,
    remember,
)

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]
REQUEST = hashlib.sha256(b"POST\n/api/v1/jobs\n{}").digest()
OTHER_REQUEST = hashlib.sha256(b'POST\n/api/v1/jobs\n{"x":1}').digest()


class Rollback(Exception):
    pass


async def test_the_first_claim_proceeds_and_a_repeat_replays(
    app_db: Database, make_organization: MakeOrganization
) -> None:
    org = await make_organization("Idem")
    async with app_db.tenant(org) as session:
        assert await claim(session, org, "user:1", "key-0001", REQUEST) is None
        await remember(session, org, "user:1", "key-0001", 201, {"id": "job-1"})

    async with app_db.tenant(org) as session:
        replay = await claim(session, org, "user:1", "key-0001", REQUEST)
    assert replay == StoredResponse(201, {"id": "job-1"})


async def test_scopes_do_not_share_keys(
    app_db: Database, make_organization: MakeOrganization
) -> None:
    org = await make_organization("IdemScopes")
    async with app_db.tenant(org) as session:
        await claim(session, org, "user:1", "key-0001", REQUEST)
        await remember(session, org, "user:1", "key-0001", 201, {})
    async with app_db.tenant(org) as session:
        assert await claim(session, org, "user:2", "key-0001", REQUEST) is None


async def test_a_different_request_with_the_same_key_is_refused(
    app_db: Database, make_organization: MakeOrganization
) -> None:
    org = await make_organization("IdemReused")
    async with app_db.tenant(org) as session:
        await claim(session, org, "user:1", "key-0001", REQUEST)
        await remember(session, org, "user:1", "key-0001", 201, {})
    with pytest.raises(IdempotencyKeyReused):
        async with app_db.tenant(org) as session:
            await claim(session, org, "user:1", "key-0001", OTHER_REQUEST)


async def test_a_concurrent_claim_waits_and_replays(
    app_db: Database, make_organization: MakeOrganization
) -> None:
    org = await make_organization("IdemWait")
    claimed, release = asyncio.Event(), asyncio.Event()

    async def first() -> None:
        async with app_db.tenant(org) as session:
            assert await claim(session, org, "user:1", "key-wait", REQUEST) is None
            claimed.set()
            await release.wait()
            await remember(session, org, "user:1", "key-wait", 201, {"n": 1})

    async def second() -> StoredResponse | None:
        await claimed.wait()
        async with app_db.tenant(org) as session:
            return await claim(session, org, "user:1", "key-wait", REQUEST)

    first_task, second_task = asyncio.create_task(first()), asyncio.create_task(second())
    await claimed.wait()
    await asyncio.sleep(0.3)
    assert not second_task.done()  # blocked on the first transaction's row
    release.set()
    await first_task
    assert await second_task == StoredResponse(201, {"n": 1})


async def test_a_rolled_back_claim_frees_the_key(
    app_db: Database, make_organization: MakeOrganization
) -> None:
    org = await make_organization("IdemRollback")
    with pytest.raises(Rollback):
        async with app_db.tenant(org) as session:
            await claim(session, org, "user:1", "key-back", REQUEST)
            raise Rollback
    async with app_db.tenant(org) as session:
        assert await claim(session, org, "user:1", "key-back", REQUEST) is None


async def test_a_claim_held_too_long_is_in_progress(
    app_db: Database, make_organization: MakeOrganization
) -> None:
    org = await make_organization("IdemBusy")
    claimed, release = asyncio.Event(), asyncio.Event()

    async def holder() -> None:
        async with app_db.tenant(org) as session:
            await claim(session, org, "user:1", "key-busy", REQUEST)
            claimed.set()
            await release.wait()

    task = asyncio.create_task(holder())
    await claimed.wait()
    try:
        with pytest.raises(IdempotencyInProgress):
            async with app_db.tenant(org) as session:
                await claim(session, org, "user:1", "key-busy", REQUEST, lock_timeout_ms=200)
    finally:
        release.set()
        await task


async def test_tenants_cannot_see_each_others_keys(
    app_db: Database, make_organization: MakeOrganization
) -> None:
    acme = await make_organization("IdemAcme")
    globex = await make_organization("IdemGlobex")
    async with app_db.tenant(acme) as session:
        await claim(session, acme, "user:1", "key-0001", REQUEST)
    async with app_db.tenant(globex) as session:
        visible = await session.scalar(
            text("SELECT count(*) FROM idempotency_keys WHERE organization_id = :org"),
            {"org": acme},
        )
    assert visible == 0


async def test_purge_removes_only_expired_keys(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    org = await make_organization("IdemPurge")
    async with app_db.tenant(org) as session:
        for key in ("key-old1", "key-new1"):
            await claim(session, org, "user:1", key, REQUEST)
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE idempotency_keys SET created_at = now() - interval '25 hours' "
                "WHERE organization_id = :org AND key = 'key-old1'"
            ),
            {"org": org},
        )
        assert await purge_idempotency_keys(conn, timedelta(hours=24)) == 1
        remaining = await conn.scalars(
            text("SELECT key FROM idempotency_keys WHERE organization_id = :org"), {"org": org}
        )
        assert remaining.all() == ["key-new1"]
