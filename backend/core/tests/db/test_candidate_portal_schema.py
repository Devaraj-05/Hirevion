"""The candidate portal's tables (SP-07b Task 1): web sessions and candidate requests."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.db.isolation import find_isolation_problems
from hirevion_core.db.session import Database
from hirevion_core.ids import uuid7
from hirevion_core.models import CandidateRequest, CandidateWebSession

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]
NOW = datetime.now(UTC)


async def _account(engine: AsyncEngine, hiring: object, email: str) -> UUID:
    account_id = uuid7()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO candidate_accounts (id, organization_id, candidate_id, email, name, "
                "status) VALUES (:id, :org, :candidate, :email, 'Asha', 'active')"
            ),
            {
                "id": account_id,
                "org": hiring.organization_id,  # type: ignore[attr-defined]
                "candidate": hiring.candidate_id,  # type: ignore[attr-defined]
                "email": email,
            },
        )
    return account_id


async def _session(engine: AsyncEngine, org: UUID, account: UUID, token_hash: bytes) -> UUID:
    session_id = uuid7()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO candidate_web_sessions (id, organization_id, account_id, token_hash, "
                "csrf_hash, last_seen_at, expires_at) VALUES (:id, :org, :account, :hash, "
                "'\\x00'::bytea, :now, :expires)"
            ),
            {
                "id": session_id,
                "org": org,
                "account": account,
                "hash": token_hash,
                "now": NOW,
                "expires": NOW + timedelta(hours=12),
            },
        )
    return session_id


async def test_the_new_tables_are_isolated(admin_engine: AsyncEngine) -> None:
    async with admin_engine.connect() as conn:
        assert await find_isolation_problems(conn) == []


async def test_candidate_sessions_are_found_by_token_without_a_tenant(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    acme = await make_organization("Acme")
    hiring = await make_hiring(acme)
    account = await _account(admin_engine, hiring, "asha.portal@example.test")
    session_id = await _session(admin_engine, acme, account, b"portal-token-hash")
    async with app_db.unscoped() as session:
        assert (await session.scalars(select(CandidateWebSession))).all() == []
        row = (
            await session.execute(
                text("SELECT * FROM auth_candidate_session(:hash)"),
                {"hash": b"portal-token-hash"},
            )
        ).one()
    assert (row.session_id, row.account_id, row.organization_id) == (session_id, account, acme)
    assert (row.account_status, row.organization_status) == ("active", "active")


async def test_candidate_sessions_and_requests_are_tenant_scoped(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    acme, globex = await make_organization("Acme"), await make_organization("Globex")
    ids = {}
    for org, name in ((acme, "acme"), (globex, "globex")):
        hiring = await make_hiring(org)
        account = await _account(admin_engine, hiring, f"{name}@example.test")
        await _session(admin_engine, org, account, f"{name}-hash".encode())
        async with app_db.tenant(org) as session:
            row = CandidateRequest(
                organization_id=org,
                account_id=account,
                candidate_id=hiring.candidate_id,
                kind="support",
                message="The app won't start",
            )
            session.add(row)
            await session.flush()
            ids[org] = row.id
    async with app_db.tenant(acme) as session:
        assert (await session.scalars(select(CandidateRequest.id))).all() == [ids[acme]]
        sessions = (await session.scalars(select(CandidateWebSession))).all()
    assert [s.organization_id for s in sessions] == [acme]


@pytest.mark.parametrize(
    ("column", "value"), [("kind", "complaint"), ("status", "pending")], ids=["kind", "status"]
)
async def test_requests_take_only_known_kinds_and_statuses(
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring,
    column: str,
    value: str,
) -> None:
    acme = await make_organization("Acme")
    hiring = await make_hiring(acme)
    account = await _account(admin_engine, hiring, f"{column}@example.test")
    values = {"kind": "support", "status": "open", column: value}
    with pytest.raises(IntegrityError):
        async with admin_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO candidate_requests (id, organization_id, account_id, "
                    "candidate_id, kind, status) VALUES (:id, :org, :account, :candidate, "
                    ":kind, :status)"
                ),
                {
                    "id": uuid7(),
                    "org": acme,
                    "account": account,
                    "candidate": hiring.candidate_id,
                    **values,
                },
            )
