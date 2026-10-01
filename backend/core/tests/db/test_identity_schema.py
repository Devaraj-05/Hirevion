"""The identity tables and the sign-in lookup functions (SP-02a, spec "Row-level security and the
sign-in lookup")."""

import hashlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.db.isolation import find_isolation_problems
from hirevion_core.db.session import Database
from hirevion_core.identity import PLATFORM_ORGANIZATION_ID
from hirevion_core.ids import uuid7
from hirevion_core.models import User, WebSession
from hirevion_core.settings import AUTH_ROLE

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]
# Stands in for an argon2id hash; these tests only check that the lookup returns it.
STORED_HASH = "$argon2id$stand-in"


async def add_user(engine: AsyncEngine, organization_id: UUID, email: str) -> UUID:
    user_id = uuid7()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO users (id, organization_id, email, name, status, password_hash) "
                "VALUES (:id, :org, :email, 'Test User', 'active', :stored)"
            ),
            {"id": user_id, "org": organization_id, "email": email, "stored": STORED_HASH},
        )
    return user_id


async def add_session(
    engine: AsyncEngine, organization_id: UUID, user_id: UUID, token: bytes
) -> UUID:
    session_id = uuid7()
    now = datetime.now(UTC)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO web_sessions (id, organization_id, user_id, token_hash, csrf_hash, "
                "last_seen_at, expires_at) VALUES (:id, :org, :user, :token, :csrf, :seen, :exp)"
            ),
            {
                "id": session_id,
                "org": organization_id,
                "user": user_id,
                "token": hashlib.sha256(token).digest(),
                "csrf": hashlib.sha256(b"csrf").digest(),
                "seen": now,
                "exp": now + timedelta(hours=12),
            },
        )
    return session_id


async def test_identity_tables_pass_the_isolation_harness(admin_engine: AsyncEngine) -> None:
    async with admin_engine.connect() as conn:
        assert await find_isolation_problems(conn) == []


async def test_users_are_tenant_scoped(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    acme = await make_organization("Acme")
    globex = await make_organization("Globex")
    ravi = await add_user(admin_engine, acme, f"ravi-{acme.hex[-8:]}@acme.example.test")
    await add_user(admin_engine, globex, f"gita-{globex.hex[-8:]}@globex.example.test")

    async with app_db.tenant(acme) as session:
        assert (await session.scalars(select(User.id))).all() == [ravi]

    with pytest.raises(DBAPIError):
        async with app_db.tenant(acme) as session:
            session.add(
                User(
                    organization_id=globex,
                    email=f"intruder-{globex.hex[-8:]}@globex.example.test",
                    name="Intruder",
                )
            )

    async with app_db.unscoped() as session:
        assert (await session.scalars(select(User.id))).all() == []
        assert (await session.scalars(select(WebSession.id))).all() == []


async def test_emails_are_unique_across_organisations(
    admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    acme = await make_organization("Acme")
    globex = await make_organization("Globex")
    email = f"shared-{acme.hex[-8:]}@example.test"
    await add_user(admin_engine, acme, email)
    with pytest.raises(IntegrityError):
        await add_user(admin_engine, globex, email.upper())


async def test_user_lookup_ignores_case_and_needs_no_tenant(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    acme = await make_organization("Acme")
    ravi = await add_user(admin_engine, acme, f"Ravi-{acme.hex[-8:]}@Acme.example.test")

    async with app_db.unscoped() as session:
        found = (
            await session.execute(
                text("SELECT * FROM auth_user_by_email(:email)"),
                {"email": f"ravi-{acme.hex[-8:]}@acme.EXAMPLE.test"},
            )
        ).one()
        missing = (
            await session.execute(
                text("SELECT * FROM auth_user_by_email(:email)"),
                {"email": "nobody@example.test"},
            )
        ).all()

    assert found.user_id == ravi
    assert found.organization_id == acme
    assert found.status == "active"
    assert found.password_hash == STORED_HASH
    assert found.organization_status == "active"
    assert missing == []


async def test_session_lookup_joins_user_and_organisation(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    acme = await make_organization("Acme")
    ravi = await add_user(admin_engine, acme, f"ravi-{acme.hex[-8:]}@acme.example.test")
    session_id = await add_session(admin_engine, acme, ravi, b"session-token")

    async with app_db.unscoped() as session:
        found = (
            await session.execute(
                text("SELECT * FROM auth_session(:hash)"),
                {"hash": hashlib.sha256(b"session-token").digest()},
            )
        ).one()
        missing = (
            await session.execute(
                text("SELECT * FROM auth_session(:hash)"),
                {"hash": hashlib.sha256(b"other").digest()},
            )
        ).all()

    assert (found.session_id, found.user_id, found.organization_id) == (session_id, ravi, acme)
    assert (found.user_status, found.organization_status) == ("active", "active")
    assert found.revoked_at is None
    assert missing == []


async def test_lookups_are_owned_by_the_auth_role_and_only_the_app_may_call_them(
    admin_engine: AsyncEngine,
) -> None:
    async with admin_engine.connect() as conn:
        functions = (
            await conn.execute(
                text(
                    "SELECT proname, prosecdef, pg_get_userbyid(proowner) AS owner "
                    "FROM pg_proc "
                    "WHERE proname IN ('auth_user_by_email', 'auth_session', 'auth_token') "
                    "ORDER BY proname"
                )
            )
        ).all()
        callers = (
            await conn.execute(
                text(
                    "SELECT has_function_privilege('hirevion_app', 'auth_session(bytea)', "
                    "'EXECUTE') AS app, has_function_privilege('hirevion_relay', "
                    "'auth_session(bytea)', 'EXECUTE') AS relay"
                )
            )
        ).one()

    assert [tuple(row) for row in functions] == [
        ("auth_session", True, AUTH_ROLE),
        ("auth_token", True, AUTH_ROLE),
        ("auth_user_by_email", True, AUTH_ROLE),
    ]
    assert (callers.app, callers.relay) == (True, False)


async def test_the_auth_role_cannot_log_in_or_bypass_row_level_security(
    admin_engine: AsyncEngine,
) -> None:
    async with admin_engine.connect() as conn:
        role = (
            await conn.execute(
                text(
                    "SELECT rolcanlogin, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = :role"
                ),
                {"role": AUTH_ROLE},
            )
        ).one()
    assert tuple(role) == (False, False, False)


async def test_harness_reports_an_auth_role_that_bypasses_rls(admin_engine: AsyncEngine) -> None:
    async with admin_engine.begin() as conn:
        await conn.execute(text(f"ALTER ROLE {AUTH_ROLE} BYPASSRLS"))
        try:
            problems = await find_isolation_problems(conn)
        finally:
            await conn.execute(text(f"ALTER ROLE {AUTH_ROLE} NOBYPASSRLS"))
    assert any(AUTH_ROLE in problem for problem in problems)


async def test_the_platform_organisation_holds_the_super_admin_role(
    admin_engine: AsyncEngine,
) -> None:
    async with admin_engine.connect() as conn:
        organisation = (
            await conn.execute(
                text("SELECT slug, status FROM organizations WHERE id = :id"),
                {"id": PLATFORM_ORGANIZATION_ID},
            )
        ).one()
        roles = (
            await conn.execute(
                text("SELECT key, system FROM roles WHERE organization_id = :id"),
                {"id": PLATFORM_ORGANIZATION_ID},
            )
        ).all()
    assert tuple(organisation) == ("platform", "active")
    assert [tuple(role) for role in roles] == [("super_admin", True)]
