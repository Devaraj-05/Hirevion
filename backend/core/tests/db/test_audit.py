"""The hash-chained, append-only audit log (master plan §7, PRD §97)."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.audit import GENESIS_HASH, AuditEntry, AuditService, ChainCheck
from hirevion_core.db.isolation import find_isolation_problems
from hirevion_core.db.partitions import ensure_monthly_partitions, month_ranges
from hirevion_core.db.session import Database
from hirevion_core.models import AuditLog
from hirevion_core.settings import APP_ROLE

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]
audit = AuditService()


def viewed(number: int) -> AuditEntry:
    return AuditEntry(action="candidate.viewed", resource_type="candidate", resource_id=str(number))


async def append_many(db: Database, org: UUID, count: int) -> list[AuditLog]:
    async with db.tenant(org) as session:
        return [await audit.append(session, org, viewed(number)) for number in range(count)]


async def test_appends_link_into_a_chain(
    app_db: Database, make_organization: MakeOrganization
) -> None:
    org = await make_organization("Chain")
    rows = await append_many(app_db, org, 3)

    assert [row.seq for row in rows] == [1, 2, 3]
    assert rows[0].prev_hash == GENESIS_HASH
    assert rows[1].prev_hash == rows[0].hash
    assert rows[2].prev_hash == rows[1].hash
    async with app_db.tenant(org) as session:
        assert await audit.verify_chain(session, org) == ChainCheck(True, 3, None)


async def test_tampering_is_detected(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    org = await make_organization("Tampered")
    await append_many(app_db, org, 3)
    async with admin_engine.begin() as conn:
        # Only a superuser can switch the append-only trigger off like this.
        await conn.execute(text("SET LOCAL session_replication_role = replica"))
        await conn.execute(
            text(
                "UPDATE audit_logs SET resource_id = 'x' WHERE organization_id = :org AND seq = 2"
            ),
            {"org": org},
        )

    async with app_db.tenant(org) as session:
        assert await audit.verify_chain(session, org) == ChainCheck(False, 2, 2)


async def test_the_app_role_cannot_rewrite_history(
    app_db: Database, make_organization: MakeOrganization
) -> None:
    org = await make_organization("Immutable")
    await append_many(app_db, org, 1)
    for statement in ("UPDATE audit_logs SET action = 'x'", "DELETE FROM audit_logs"):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with app_db.tenant(org) as session:
                await session.execute(text(statement))


async def test_the_trigger_stops_even_the_admin(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    org = await make_organization("Trigger")
    await append_many(app_db, org, 1)
    for statement in (
        "UPDATE audit_logs SET action = 'x' WHERE organization_id = :org",
        "DELETE FROM audit_logs WHERE organization_id = :org",
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            async with admin_engine.begin() as conn:
                await conn.execute(text(statement), {"org": org})


async def test_concurrent_appends_stay_in_sequence(
    app_db: Database, make_organization: MakeOrganization
) -> None:
    org = await make_organization("Busy")

    async def append_one(number: int) -> None:
        async with app_db.tenant(org) as session:
            await audit.append(session, org, viewed(number))

    await asyncio.gather(*(append_one(number) for number in range(20)))

    async with app_db.tenant(org) as session:
        seqs = (await session.scalars(select(AuditLog.seq).order_by(AuditLog.seq))).all()
        check = await audit.verify_chain(session, org)
    assert seqs == list(range(1, 21))
    assert check == ChainCheck(True, 20, None)


async def test_an_organisation_cannot_read_another_audit_log(
    app_db: Database, make_organization: MakeOrganization
) -> None:
    acme = await make_organization("AuditAcme")
    globex = await make_organization("AuditGlobex")
    await append_many(app_db, acme, 2)

    async with app_db.tenant(globex) as session:
        rows = await session.scalars(select(AuditLog.id).where(AuditLog.organization_id == acme))
        assert rows.all() == []


async def test_an_organisation_cannot_write_into_another_audit_log(
    app_db: Database, make_organization: MakeOrganization
) -> None:
    acme = await make_organization("WriterAcme")
    globex = await make_organization("WriterGlobex")
    with pytest.raises(DBAPIError, match="row-level security"):
        async with app_db.tenant(globex) as session:
            await audit.append(session, acme, viewed(1))


async def test_rows_outside_the_monthly_partitions_land_in_the_default(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    org = await make_organization("Future")
    async with app_db.tenant(org) as session:
        row = await audit.append(session, org, viewed(1), now=datetime(2030, 1, 15, tzinfo=UTC))

    async with admin_engine.connect() as conn:
        partition = await conn.scalar(
            text("SELECT tableoid::regclass::text FROM audit_logs WHERE id = :id"), {"id": row.id}
        )
    assert partition == "audit_logs_default"
    async with app_db.tenant(org) as session:
        assert await audit.verify_chain(session, org) == ChainCheck(True, 1, None)


async def test_migrate_created_this_month_and_is_idempotent(admin_engine: AsyncEngine) -> None:
    today = datetime.now(UTC).date()
    suffix = month_ranges(today, 1)[0][0]
    async with admin_engine.begin() as conn:
        assert await ensure_monthly_partitions(conn, "audit_logs", today, 3) == []
        assert await conn.scalar(
            text("SELECT to_regclass(:name) IS NOT NULL"), {"name": f"audit_logs_{suffix}"}
        )


async def test_harness_reports_a_partition_the_app_role_can_query(
    admin_engine: AsyncEngine,
) -> None:
    # connect() without commit: everything below is rolled back on exit.
    async with admin_engine.connect() as conn:
        created = await ensure_monthly_partitions(conn, "audit_logs", date(2031, 1, 1), 1)
        assert created == ["audit_logs_y2031m01"]
        await conn.execute(text(f"GRANT SELECT ON audit_logs_y2031m01 TO {APP_ROLE}"))
        problems = await find_isolation_problems(conn)
    assert "audit_logs_y2031m01: partition is directly accessible to hirevion_app" in problems
