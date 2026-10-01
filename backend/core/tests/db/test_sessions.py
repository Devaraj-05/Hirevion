"""Server-side web sessions and system roles (SP-02 spec, "Sign-in, sessions and CSRF")."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.db.session import Database
from hirevion_core.identity import PLATFORM_ORGANIZATION_ID
from hirevion_core.identity.sessions import (
    SessionContext,
    create_session,
    hash_token,
    list_sessions,
    resolve_session,
    revoke_all_sessions,
    revoke_session,
)
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.models import Role

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]
SETTINGS = IdentitySettings()
NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


async def start(db: Database, organization_id: UUID, user_id: UUID, at: datetime = NOW):
    async with db.tenant(organization_id) as session:
        return await create_session(
            session,
            user_id=user_id,
            organization_id=organization_id,
            ip="203.0.113.7",
            user_agent="Test browser",
            settings=SETTINGS,
            now=at,
        )


async def test_organisations_get_their_system_roles(
    app_db: Database, make_organization: MakeOrganization
) -> None:
    acme = await make_organization("Acme")
    async with app_db.tenant(acme) as session:
        keys = sorted((await session.scalars(select(Role.key).where(Role.system))).all())
    assert keys == ["hiring_manager", "interviewer", "org_admin", "recruiter"]

    async with app_db.tenant(PLATFORM_ORGANIZATION_ID) as session:
        platform = (await session.scalars(select(Role.key))).all()
    assert platform == ["super_admin"]


async def test_a_new_session_resolves_and_stores_only_hashes(
    app_db: Database, make_organization: MakeOrganization, make_user
) -> None:
    acme = await make_organization("Acme")
    ravi = await make_user(acme)
    token, csrf, row = await start(app_db, acme, ravi)

    resolved = await resolve_session(
        app_db, token, settings=SETTINGS, now=NOW + timedelta(minutes=5)
    )
    assert resolved == SessionContext(row.id, ravi, acme, hash_token(csrf))
    assert row.token_hash == hash_token(token)
    assert token.encode() not in row.token_hash and csrf.encode() not in row.csrf_hash
    assert await resolve_session(app_db, "not-a-token", settings=SETTINGS, now=NOW) is None


async def test_an_idle_session_expires_after_thirty_minutes(
    app_db: Database, make_organization: MakeOrganization, make_user
) -> None:
    acme = await make_organization("Acme")
    token, _, _ = await start(app_db, acme, await make_user(acme))
    later = NOW + timedelta(minutes=31)
    assert await resolve_session(app_db, token, settings=SETTINGS, now=later) is None


async def test_a_busy_session_still_ends_after_twelve_hours(
    app_db: Database, make_organization: MakeOrganization, make_user
) -> None:
    acme = await make_organization("Acme")
    token, _, _ = await start(app_db, acme, await make_user(acme))
    for minutes in range(25, 12 * 60, 25):
        at = NOW + timedelta(minutes=minutes)
        assert await resolve_session(app_db, token, settings=SETTINGS, now=at) is not None
    end = NOW + timedelta(hours=12, seconds=1)
    assert await resolve_session(app_db, token, settings=SETTINGS, now=end) is None


async def test_revoked_disabled_or_suspended_sessions_do_not_resolve(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user,
) -> None:
    acme = await make_organization("Acme")
    ravi = await make_user(acme)
    revoked, _, row = await start(app_db, acme, ravi)
    async with app_db.tenant(acme) as session:
        assert await revoke_session(session, user_id=ravi, session_id=row.id, now=NOW)
    assert await resolve_session(app_db, revoked, settings=SETTINGS, now=NOW) is None

    gita = await make_user(acme)
    disabled, _, _ = await start(app_db, acme, gita)
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET status = 'disabled' WHERE id = :id"), {"id": gita}
        )
    assert await resolve_session(app_db, disabled, settings=SETTINGS, now=NOW) is None

    globex = await make_organization("Globex")
    suspended, _, _ = await start(app_db, globex, await make_user(globex))
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE organizations SET status = 'suspended' WHERE id = :id"), {"id": globex}
        )
    assert await resolve_session(app_db, suspended, settings=SETTINGS, now=NOW) is None


async def test_last_seen_is_written_at_most_once_a_minute(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user,
) -> None:
    acme = await make_organization("Acme")
    token, _, row = await start(app_db, acme, await make_user(acme))

    async def last_seen() -> datetime:
        async with admin_engine.connect() as conn:
            value = await conn.scalar(
                text("SELECT last_seen_at FROM web_sessions WHERE id = :id"), {"id": row.id}
            )
        assert isinstance(value, datetime)
        return value

    await resolve_session(app_db, token, settings=SETTINGS, now=NOW + timedelta(seconds=30))
    assert await last_seen() == NOW
    await resolve_session(app_db, token, settings=SETTINGS, now=NOW + timedelta(seconds=90))
    assert await last_seen() == NOW + timedelta(seconds=90)


async def test_revoking_everything_else_keeps_this_session(
    app_db: Database, make_organization: MakeOrganization, make_user
) -> None:
    acme = await make_organization("Acme")
    ravi = await make_user(acme)
    this, _, this_row = await start(app_db, acme, ravi)
    other, _, _ = await start(app_db, acme, ravi)
    third, _, _ = await start(app_db, acme, ravi)

    async with app_db.tenant(acme) as session:
        ended = await revoke_all_sessions(
            session, user_id=ravi, except_session=this_row.id, now=NOW
        )
    assert ended == 2
    assert await resolve_session(app_db, this, settings=SETTINGS, now=NOW) is not None
    for token in (other, third):
        assert await resolve_session(app_db, token, settings=SETTINGS, now=NOW) is None


async def test_one_user_cannot_revoke_anothers_session(
    app_db: Database, make_organization: MakeOrganization, make_user
) -> None:
    acme = await make_organization("Acme")
    ravi = await make_user(acme)
    gita = await make_user(acme)
    token, _, row = await start(app_db, acme, gita)
    async with app_db.tenant(acme) as session:
        assert not await revoke_session(session, user_id=ravi, session_id=row.id, now=NOW)
    assert await resolve_session(app_db, token, settings=SETTINGS, now=NOW) is not None


async def test_the_session_list_shows_live_sessions_newest_first(
    app_db: Database, make_organization: MakeOrganization, make_user
) -> None:
    acme = await make_organization("Acme")
    ravi = await make_user(acme)
    _, _, old = await start(app_db, acme, ravi, at=NOW)
    _, _, new = await start(app_db, acme, ravi, at=NOW + timedelta(minutes=10))
    _, _, ended = await start(app_db, acme, ravi, at=NOW + timedelta(minutes=5))
    async with app_db.tenant(acme) as session:
        await revoke_session(session, user_id=ravi, session_id=ended.id, now=NOW)
        live = await list_sessions(
            session, user_id=ravi, settings=SETTINGS, now=NOW + timedelta(minutes=20)
        )
    assert [s.id for s in live] == [new.id, old.id]
