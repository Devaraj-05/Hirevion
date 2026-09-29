"""The outbox delivery test (master plan SP-01 exit criterion): events committed with the
business change reach Valkey Streams exactly when that change commits."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from uuid import UUID

import pytest
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.db.session import Database
from hirevion_core.models import OutboxEvent
from hirevion_core.outbox import OutboxRelay, publish_event, stream_name

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("empty_outbox")]

MakeOrganization = Callable[[str], Awaitable[UUID]]


class Rollback(Exception):
    pass


async def outbox_row(admin_engine: AsyncEngine, event_id: UUID) -> tuple[object, int]:
    async with admin_engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT published_at, attempts FROM outbox_events WHERE id = :id"),
                {"id": event_id},
            )
        ).one()
    return row.published_at, row.attempts


async def test_a_committed_event_reaches_a_consumer_group(
    app_db: Database,
    relay_db: Database,
    valkey: Redis,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
) -> None:
    org = await make_organization("Outbox")
    async with app_db.tenant(org) as session:
        event_id = await publish_event(
            session, org, "interview.completed", {"interview_id": "i-1", "score": 7}, key="i-1"
        )

    assert await OutboxRelay(relay_db, valkey).run_once() == 1

    stream = stream_name("interview.completed")
    await valkey.xgroup_create(stream, "reports", id="0")
    [(_, [(_, fields)])] = await valkey.xreadgroup("reports", "worker-1", {stream: ">"})
    assert fields["id"] == str(event_id)
    assert fields["org"] == str(org)
    assert fields["topic"] == "interview.completed"
    assert fields["key"] == "i-1"
    assert json.loads(fields["payload"]) == {"interview_id": "i-1", "score": 7}
    published_at, attempts = await outbox_row(admin_engine, event_id)
    assert published_at is not None
    assert attempts == 1


async def test_a_rolled_back_event_is_never_published(
    app_db: Database, relay_db: Database, valkey: Redis, make_organization: MakeOrganization
) -> None:
    org = await make_organization("Rollback")
    with pytest.raises(Rollback):
        async with app_db.tenant(org) as session:
            await publish_event(session, org, "interview.started", {"interview_id": "i-2"})
            raise Rollback

    assert await OutboxRelay(relay_db, valkey).run_once() == 0
    assert await valkey.exists(stream_name("interview.started")) == 0


async def test_two_relays_publish_each_event_exactly_once(
    app_db: Database, relay_db: Database, valkey: Redis, make_organization: MakeOrganization
) -> None:
    org = await make_organization("Parallel")
    async with app_db.tenant(org) as session:
        published = [
            await publish_event(session, org, "candidate.created", {"n": number})
            for number in range(30)
        ]

    async def drain(relay: OutboxRelay) -> int:
        total = 0
        while count := await relay.run_once():
            total += count
        return total

    counts = await asyncio.gather(
        drain(OutboxRelay(relay_db, valkey, batch=4)), drain(OutboxRelay(relay_db, valkey, batch=4))
    )
    assert sum(counts) == 30
    entries = await valkey.xrange(stream_name("candidate.created"))
    assert sorted(fields["id"] for _, fields in entries) == sorted(map(str, published))


async def test_a_failed_publish_stays_pending_and_is_counted(
    app_db: Database,
    relay_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
) -> None:
    org = await make_organization("Unreachable")
    async with app_db.tenant(org) as session:
        event_id = await publish_event(session, org, "report.ready", {"report_id": "r-1"})

    unreachable = Redis(
        host="127.0.0.1", port=1, socket_connect_timeout=0.5, retry=Retry(NoBackoff(), 0)
    )
    try:
        with pytest.raises(RedisError):
            await OutboxRelay(relay_db, unreachable).run_once()
    finally:
        await unreachable.aclose()
    assert await outbox_row(admin_engine, event_id) == (None, 1)


async def test_run_forever_publishes_until_stopped(
    app_db: Database, relay_db: Database, valkey: Redis, make_organization: MakeOrganization
) -> None:
    org = await make_organization("Forever")
    stop = asyncio.Event()
    relay = asyncio.create_task(OutboxRelay(relay_db, valkey).run_forever(stop, poll=0.05))
    async with app_db.tenant(org) as session:
        await publish_event(session, org, "candidate.shortlisted", {"candidate_id": "c-1"})

    stream = stream_name("candidate.shortlisted")
    async with asyncio.timeout(5):
        while not await valkey.exists(stream):
            await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(relay, 5)
    assert await valkey.xlen(stream) == 1


async def test_the_relay_role_cannot_read_the_audit_log(relay_db: Database) -> None:
    with pytest.raises(DBAPIError, match="permission denied"):
        async with relay_db.unscoped() as session:
            await session.execute(text("SELECT 1 FROM audit_logs"))


async def test_the_relay_role_cannot_rewrite_an_event(relay_db: Database) -> None:
    with pytest.raises(DBAPIError, match="permission denied"):
        async with relay_db.unscoped() as session:
            await session.execute(text("UPDATE outbox_events SET payload = '{}'::jsonb"))


async def test_tenants_see_only_their_own_events(
    app_db: Database, make_organization: MakeOrganization
) -> None:
    acme = await make_organization("EventsAcme")
    globex = await make_organization("EventsGlobex")
    async with app_db.tenant(acme) as session:
        await publish_event(session, acme, "candidate.created", {"n": 1})

    async with app_db.tenant(globex) as session:
        rows = await session.scalars(
            select(OutboxEvent.id).where(OutboxEvent.organization_id == acme)
        )
        assert rows.all() == []
    with pytest.raises(DBAPIError, match="permission denied"):
        async with app_db.tenant(acme) as session:
            await session.execute(text("UPDATE outbox_events SET published_at = now()"))
