"""The sign-in, password and email flows (SP-02 spec, "Sign-in, sessions and CSRF")."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from argon2 import PasswordHasher
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.db.session import Database
from hirevion_core.identity import PLATFORM_ORGANIZATION_ID
from hirevion_core.identity import service as service_module
from hirevion_core.identity.passwords import PasswordPolicy, hash_password, verify_password
from hirevion_core.identity.permissions import PERMISSIONS, permissions_for
from hirevion_core.identity.service import AuthService, LoginOk, LoginRefused
from hirevion_core.identity.sessions import resolve_session
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.identity.tokens import issue_token
from hirevion_core.ids import uuid7

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]
SETTINGS = IdentitySettings(web_origin="https://app.hirevion.localhost")
PASSWORD = "correct horse battery staple"  # noqa: S105 (a test input)
NEW_PASSWORD = "a brand new long passphrase"  # noqa: S105 (a test input)
WHERE = {"ip": "203.0.113.7", "user_agent": "Test browser"}


class NoBreaches:
    async def is_breached(self, password: str) -> bool:
        return False


@pytest.fixture
def auth(app_db: Database, valkey: Redis) -> AuthService:
    return AuthService(app_db, valkey, policy=PasswordPolicy(NoBreaches()), settings=SETTINGS)


def email() -> str:
    return f"user-{uuid7().hex[-12:]}@acme.example.test"


async def audit_actions(engine: AsyncEngine, organization_id: UUID) -> list[str]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT action FROM audit_logs WHERE organization_id = :org ORDER BY seq"),
            {"org": organization_id},
        )
        return [row.action for row in rows]


async def mails_to(engine: AsyncEngine, address: str) -> list[dict[str, Any]]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT payload FROM outbox_events WHERE topic = 'mail' "
                "AND payload->>'to' = :to ORDER BY created_at"
            ),
            {"to": address},
        )
        return [row.payload for row in rows]


def token_from(mail: dict[str, Any]) -> str:
    link: str = mail["context"]["link"]
    return link.rsplit("/", 1)[1]


async def signed_in(auth: AuthService, address: str, password: str = PASSWORD) -> LoginOk:
    result = await auth.login(address, password, **WHERE)
    assert isinstance(result, LoginOk)
    return result


async def test_signing_in_creates_a_session_and_is_audited(
    auth: AuthService,
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user,
) -> None:
    acme = await make_organization("Acme")
    address = email()
    await make_user(acme, email=address, password_hash=hash_password(PASSWORD))

    ok = await signed_in(auth, address.upper())
    assert (
        await resolve_session(app_db, ok.session_token, settings=SETTINGS, now=datetime.now(UTC))
        == ok.context
    )
    assert await audit_actions(admin_engine, acme) == ["auth.login.succeeded"]


async def test_a_weaker_hash_is_upgraded_at_sign_in(
    auth: AuthService, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_user
) -> None:
    acme = await make_organization("Acme")
    address = email()
    weak = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash(PASSWORD)
    ravi = await make_user(acme, email=address, password_hash=weak)
    await signed_in(auth, address)
    async with admin_engine.connect() as conn:
        stored = await conn.scalar(
            text("SELECT password_hash FROM users WHERE id = :id"), {"id": ravi}
        )
    assert stored != weak
    assert verify_password(stored, PASSWORD) == (True, False)


async def test_a_wrong_password_is_refused_and_audited(
    auth: AuthService, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_user
) -> None:
    acme = await make_organization("Acme")
    address = email()
    await make_user(acme, email=address, password_hash=hash_password(PASSWORD))
    assert await auth.login(address, "the wrong password entirely", **WHERE) == LoginRefused(None)
    assert await audit_actions(admin_engine, acme) == ["auth.login.failed"]


async def test_an_unknown_email_gets_the_same_answer_and_the_same_work(
    auth: AuthService, monkeypatch: pytest.MonkeyPatch
) -> None:
    checked: list[str | None] = []
    real = service_module.verify_password_in_thread

    async def spy(stored: str | None, password: str) -> tuple[bool, bool]:
        checked.append(stored)
        return await real(stored, password)

    monkeypatch.setattr(service_module, "verify_password_in_thread", spy)
    assert await auth.login("nobody@example.test", PASSWORD, **WHERE) == LoginRefused(None)
    assert checked == [None]


async def test_five_failures_lock_the_account_even_against_the_right_password(
    auth: AuthService, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_user
) -> None:
    acme = await make_organization("Acme")
    address = email()
    await make_user(acme, email=address, password_hash=hash_password(PASSWORD))
    for _ in range(4):
        assert await auth.login(address, "wrong password attempt", **WHERE) == LoginRefused(None)
    assert await auth.login(address, "wrong password attempt", **WHERE) == LoginRefused(60)

    locked = await auth.login(address, PASSWORD, **WHERE)
    assert isinstance(locked, LoginRefused) and locked.retry_after is not None
    assert "auth.lockout.started" in await audit_actions(admin_engine, acme)


@pytest.mark.parametrize("status", ["invited", "disabled"])
async def test_only_active_users_sign_in(
    auth: AuthService, make_organization: MakeOrganization, make_user, status: str
) -> None:
    acme = await make_organization("Acme")
    address = email()
    await make_user(acme, email=address, status=status, password_hash=hash_password(PASSWORD))
    assert await auth.login(address, PASSWORD, **WHERE) == LoginRefused(None)


async def test_a_suspended_organisation_cannot_sign_in(
    auth: AuthService, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_user
) -> None:
    acme = await make_organization("Acme")
    address = email()
    await make_user(acme, email=address, password_hash=hash_password(PASSWORD))
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE organizations SET status = 'suspended' WHERE id = :id"), {"id": acme}
        )
    assert await auth.login(address, PASSWORD, **WHERE) == LoginRefused(None)


async def test_signing_out_ends_the_session(
    auth: AuthService,
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user,
) -> None:
    acme = await make_organization("Acme")
    address = email()
    await make_user(acme, email=address, password_hash=hash_password(PASSWORD))
    ok = await signed_in(auth, address)
    await auth.logout(ok.context, **WHERE)
    assert (
        await resolve_session(app_db, ok.session_token, settings=SETTINGS, now=datetime.now(UTC))
        is None
    )
    assert (await audit_actions(admin_engine, acme))[-1] == "auth.logout"


async def test_changing_the_password(
    auth: AuthService,
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user,
) -> None:
    acme = await make_organization("Acme")
    address = email()
    await make_user(acme, email=address, password_hash=hash_password(PASSWORD))
    this = await signed_in(auth, address)
    other = await signed_in(auth, address)

    assert await auth.change_password(this.context, "not it", NEW_PASSWORD, **WHERE) == [
        "wrong_current"
    ]
    assert await auth.change_password(this.context, PASSWORD, "too short", **WHERE) == ["too_short"]
    assert await auth.change_password(this.context, PASSWORD, NEW_PASSWORD, **WHERE) is None

    now = datetime.now(UTC)
    assert await resolve_session(app_db, this.session_token, settings=SETTINGS, now=now)
    assert await resolve_session(app_db, other.session_token, settings=SETTINGS, now=now) is None
    assert isinstance(await auth.login(address, PASSWORD, **WHERE), LoginRefused)
    await signed_in(auth, address, NEW_PASSWORD)
    assert [m["template"] for m in await mails_to(admin_engine, address)] == ["password_changed"]
    assert "auth.password.changed" in await audit_actions(admin_engine, acme)


async def test_a_reset_for_an_unknown_email_sends_nothing(
    auth: AuthService, admin_engine: AsyncEngine
) -> None:
    await auth.request_reset("nobody@example.test", **WHERE)
    assert await mails_to(admin_engine, "nobody@example.test") == []


async def test_resetting_a_forgotten_password(
    auth: AuthService,
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user,
) -> None:
    acme = await make_organization("Acme")
    address = email()
    await make_user(acme, email=address, password_hash=hash_password(PASSWORD))
    before = await signed_in(auth, address)

    await auth.request_reset(address, **WHERE)
    [mail] = await mails_to(admin_engine, address)
    assert mail["template"] == "reset_password"
    assert mail["context"]["link"].startswith("https://app.hirevion.localhost/reset-password/")
    token = token_from(mail)

    # A weak password is refused, and the link still works afterwards.
    assert await auth.reset_password(token, "too short", **WHERE) == ["too_short"]
    assert await auth.reset_password(token, NEW_PASSWORD, **WHERE) is None
    assert await auth.reset_password(token, NEW_PASSWORD, **WHERE) == ["invalid_token"]

    assert (
        await resolve_session(
            app_db, before.session_token, settings=SETTINGS, now=datetime.now(UTC)
        )
        is None
    )
    assert isinstance(await auth.login(address, PASSWORD, **WHERE), LoginRefused)
    await signed_in(auth, address, NEW_PASSWORD)
    templates = [m["template"] for m in await mails_to(admin_engine, address)]
    assert templates == ["reset_password", "password_changed"]
    actions = await audit_actions(admin_engine, acme)
    assert "auth.password.reset_requested" in actions and "auth.password.reset" in actions


async def test_changing_the_email_address(
    auth: AuthService, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_user
) -> None:
    acme = await make_organization("Acme")
    old, new, taken = email(), email(), email()
    await make_user(acme, email=old, password_hash=hash_password(PASSWORD))
    await make_user(acme, email=taken)
    ok = await signed_in(auth, old)

    assert await auth.request_email_change(ok.context, new, "not it", **WHERE) == "wrong_password"
    assert await auth.request_email_change(ok.context, taken, PASSWORD, **WHERE) == "unavailable"
    assert await mails_to(admin_engine, taken) == []

    assert await auth.request_email_change(ok.context, new, PASSWORD, **WHERE) == "ok"
    [verify] = await mails_to(admin_engine, new)
    [notice] = await mails_to(admin_engine, old)
    assert (verify["template"], notice["template"]) == ("verify_email", "email_change_requested")

    assert await auth.verify_email(token_from(verify), **WHERE) is True
    assert await auth.verify_email(token_from(verify), **WHERE) is False
    await signed_in(auth, new)
    assert "auth.email.verified" in await audit_actions(admin_engine, acme)


async def test_an_invited_user_sets_a_first_password(
    auth: AuthService, app_db: Database, make_organization: MakeOrganization, make_user
) -> None:
    acme = await make_organization("Acme")
    address = email()
    gita = await make_user(acme, email=address, status="invited")
    async with app_db.tenant(acme) as session:
        token = await issue_token(
            session,
            organization_id=acme,
            user_id=gita,
            purpose="set_password",
            ttl=timedelta(hours=72),
            now=datetime.now(UTC),
        )
    assert await auth.set_password(token, NEW_PASSWORD, **WHERE) is None
    assert await auth.set_password(token, NEW_PASSWORD, **WHERE) == ["invalid_token"]
    await signed_in(auth, address, NEW_PASSWORD)


async def test_the_session_view_matches_the_web_contract(
    auth: AuthService, make_organization: MakeOrganization, make_user
) -> None:
    acme = await make_organization("Acme")
    address = email()
    await make_user(
        acme,
        email=address,
        name="Ravi Kumar",
        password_hash=hash_password(PASSWORD),
        roles=["recruiter"],
    )
    view = await auth.session_view((await signed_in(auth, address)).context)
    assert view.user.name == "Ravi Kumar" and view.user.email == address
    assert view.organization is not None and view.organization.id == acme
    assert view.roles == ["recruiter"]
    assert view.permissions == permissions_for(["recruiter"])

    admin = email()
    await make_user(
        PLATFORM_ORGANIZATION_ID,
        email=admin,
        password_hash=hash_password(PASSWORD),
        roles=["super_admin"],
    )
    platform = await auth.session_view((await signed_in(auth, admin)).context)
    assert platform.organization is None
    assert platform.permissions == list(PERMISSIONS)


async def test_listing_and_ending_sessions(
    auth: AuthService, app_db: Database, make_organization: MakeOrganization, make_user
) -> None:
    acme = await make_organization("Acme")
    address = email()
    await make_user(acme, email=address, password_hash=hash_password(PASSWORD))
    this = await signed_in(auth, address)
    other = await signed_in(auth, address)
    third = await signed_in(auth, address)

    listed = await auth.list_sessions(this.context)
    assert {s.id for s in listed} == {
        this.context.session_id,
        other.context.session_id,
        third.context.session_id,
    }
    assert [s.current for s in listed if s.id == this.context.session_id] == [True]

    assert await auth.revoke_session(this.context, other.context.session_id, **WHERE) is True
    assert await auth.revoke_other_sessions(this.context, **WHERE) == 1
    now = datetime.now(UTC)
    assert await resolve_session(app_db, third.session_token, settings=SETTINGS, now=now) is None
    assert await resolve_session(app_db, this.session_token, settings=SETTINGS, now=now)


async def test_stepping_up_with_the_right_password_marks_the_session(
    auth: AuthService,
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_user,
) -> None:
    acme = await make_organization("Acme")
    address = email()
    await make_user(acme, email=address, password_hash=hash_password(PASSWORD))
    signed = await signed_in(auth, address)

    assert await auth.step_up(signed.context, PASSWORD, **WHERE) == "ok"

    now = datetime.now(UTC)
    resolved = await resolve_session(app_db, signed.session_token, settings=SETTINGS, now=now)
    assert resolved is not None and resolved.stepped_up_at is not None
    assert now - resolved.stepped_up_at < timedelta(minutes=1)
    assert "auth.step_up.succeeded" in await audit_actions(admin_engine, acme)


async def test_wrong_step_up_passwords_count_towards_the_sign_in_lockout(
    auth: AuthService, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_user
) -> None:
    acme = await make_organization("Acme")
    address = email()
    await make_user(acme, email=address, password_hash=hash_password(PASSWORD))
    signed = await signed_in(auth, address)

    for _ in range(4):
        assert await auth.step_up(signed.context, "not my password at all", **WHERE) == (
            "wrong_password"
        )
    assert await auth.step_up(signed.context, "not my password at all", **WHERE) == (
        LoginRefused(60)
    )
    # Locked: even the right password is refused, here and at sign-in.
    assert isinstance(await auth.step_up(signed.context, PASSWORD, **WHERE), LoginRefused)
    assert isinstance(await auth.login(address, PASSWORD, **WHERE), LoginRefused)
    actions = await audit_actions(admin_engine, acme)
    assert actions.count("auth.step_up.failed") == 5
    assert "auth.lockout.started" in actions
