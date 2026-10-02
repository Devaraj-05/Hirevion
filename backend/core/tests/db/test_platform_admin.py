"""Super admins create, suspend and reactivate organisations (PRD §6 "Super Admin"; plan
Task 9). Each action changes one organisation and is recorded in its chain and the platform's,
in one transaction."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.access import platform
from hirevion_core.access.actor import Actor
from hirevion_core.access.errors import Conflict, Invalid
from hirevion_core.audit import AuditService
from hirevion_core.db.session import Database
from hirevion_core.identity import PLATFORM_ORGANIZATION_ID
from hirevion_core.identity.passwords import PasswordPolicy, hash_password
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.identity.service import AuthService, LoginOk, LoginRefused
from hirevion_core.identity.sessions import resolve_session
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.ids import uuid7
from hirevion_core.models import Role, User

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]
SETTINGS = IdentitySettings(web_origin="https://app.hirevion.localhost")
PASSWORD = "correct horse battery staple"  # noqa: S105 (a test input)
WHERE = {"ip": "203.0.113.7", "user_agent": "Test browser"}


class NoBreaches:
    async def is_breached(self, password: str) -> bool:
        return False


def slug() -> str:
    return f"initech-{uuid7().hex[-8:]}"


def email() -> str:
    return f"admin-{uuid7().hex[-12:]}@initech.example.test"


async def actions(engine: AsyncEngine, organization_id: UUID) -> list[tuple[str, dict[str, Any]]]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT action, details FROM audit_logs WHERE organization_id = :org ORDER BY seq"
            ),
            {"org": organization_id},
        )
        return [(row.action, row.details) for row in rows]


@pytest.fixture
async def super_admin(make_user) -> Actor:
    user = await make_user(PLATFORM_ORGANIZATION_ID, name="Sam Platform", roles=["super_admin"])
    return Actor(user, PLATFORM_ORGANIZATION_ID, frozenset(permissions_for(["super_admin"])))


@pytest.fixture
def auth(app_db: Database, valkey: Redis) -> AuthService:
    return AuthService(app_db, valkey, policy=PasswordPolicy(NoBreaches()), settings=SETTINGS)


async def create(app_db: Database, actor: Actor, **values: str) -> platform.OrganizationListing:
    arguments = {
        "name": "Initech",
        "slug": slug(),
        "admin_name": "Ian Admin",
        "admin_email": email(),
    }
    arguments.update(values)
    async with app_db.tenant(PLATFORM_ORGANIZATION_ID) as session:
        return await platform.create_organization(session, actor, settings=SETTINGS, **arguments)


async def test_creating_an_organisation_invites_its_first_admin(
    app_db: Database, admin_engine: AsyncEngine, super_admin: Actor
) -> None:
    address = email()
    created = await create(app_db, super_admin, admin_email=address)
    assert (created.name, created.status, created.user_count) == ("Initech", "active", 1)

    async with app_db.tenant(created.id) as session:
        keys = sorted(k for k in (await session.scalars(select(Role.key))).all() if k)
        admin = (await session.scalars(select(User))).one()
    assert keys == ["hiring_manager", "interviewer", "org_admin", "recruiter"]
    assert (admin.email, admin.status) == (address, "invited")

    async with admin_engine.connect() as conn:
        mail = await conn.scalar(
            text("SELECT payload FROM outbox_events WHERE payload->>'to' = :to"), {"to": address}
        )
    assert mail["template"] == "invitation"
    assert mail["context"]["inviter"] == "Sam Platform"

    created_entries = [
        a for a, _ in await actions(admin_engine, created.id) if a.startswith("platform.")
    ]
    assert created_entries == ["platform.organization.created"]
    platform_actions = [a for a, _ in await actions(admin_engine, PLATFORM_ORGANIZATION_ID)]
    assert platform_actions[-1] == "platform.organization.created"
    audit = AuditService()
    for organization_id in (created.id, PLATFORM_ORGANIZATION_ID):
        async with app_db.tenant(organization_id) as session:
            assert (await audit.verify_chain(session, organization_id)).ok


async def test_slugs_are_checked_and_unique(app_db: Database, super_admin: Actor) -> None:
    taken = slug()
    await create(app_db, super_admin, slug=taken)
    with pytest.raises(Conflict) as clash:
        await create(app_db, super_admin, slug=taken)
    assert (clash.value.code, clash.value.field) == ("slug-taken", "slug")
    for bad in ("platform", "Has Caps", "-edge", "a"):
        with pytest.raises(Invalid) as refusal:
            await create(app_db, super_admin, slug=bad)
        assert refusal.value.field == "slug"


async def test_a_first_admin_address_in_use_points_at_its_field(
    app_db: Database, super_admin: Actor, make_organization: MakeOrganization, make_user
) -> None:
    taken = email()
    await make_user(await make_organization("Globex"), email=taken)
    with pytest.raises(Conflict) as clash:
        await create(app_db, super_admin, admin_email=taken)
    assert (clash.value.code, clash.value.field) == ("email-taken", "admin_email")


async def test_suspending_ends_sessions_and_sign_in_until_reactivated(
    app_db: Database,
    admin_engine: AsyncEngine,
    super_admin: Actor,
    auth: AuthService,
    make_organization: MakeOrganization,
    make_user,
) -> None:
    globex = await make_organization("Globex")
    address = email()
    await make_user(
        globex, email=address, password_hash=hash_password(PASSWORD), roles=["recruiter"]
    )
    signed = await auth.login(address, PASSWORD, **WHERE)
    assert isinstance(signed, LoginOk)

    async with app_db.tenant(PLATFORM_ORGANIZATION_ID) as session:
        suspended = await platform.set_organization_status(
            session, super_admin, globex, suspended=True, reason="Unpaid invoice"
        )
    assert suspended.status == "suspended"
    assert (
        await resolve_session(
            app_db, signed.session_token, settings=SETTINGS, now=datetime.now(UTC)
        )
        is None
    )
    assert isinstance(await auth.login(address, PASSWORD, **WHERE), LoginRefused)
    suspension = [d for a, d in await actions(admin_engine, globex) if a.endswith("suspended")]
    assert suspension[0]["reason"] == "Unpaid invoice"

    async with app_db.tenant(PLATFORM_ORGANIZATION_ID) as session:
        await platform.set_organization_status(
            session, super_admin, globex, suspended=False, reason=None
        )
    assert isinstance(await auth.login(address, PASSWORD, **WHERE), LoginOk)


async def test_the_platform_itself_is_never_suspended(app_db: Database, super_admin: Actor) -> None:
    with pytest.raises(Conflict) as refusal:
        async with app_db.tenant(PLATFORM_ORGANIZATION_ID) as session:
            await platform.set_organization_status(
                session, super_admin, PLATFORM_ORGANIZATION_ID, suspended=True, reason=None
            )
    assert refusal.value.code == "platform-organization"


async def test_another_admin_can_be_invited_when_the_first_invitation_lapsed(
    app_db: Database, admin_engine: AsyncEngine, super_admin: Actor
) -> None:
    created = await create(app_db, super_admin)
    second = email()
    async with app_db.tenant(PLATFORM_ORGANIZATION_ID) as session:
        await platform.invite_organization_admin(
            session, super_admin, created.id, name="Second Admin", email=second, settings=SETTINGS
        )
    async with app_db.tenant(created.id) as session:
        emails = sorted((await session.scalars(select(User.email))).all())
    assert second in emails
    assert (await actions(admin_engine, PLATFORM_ORGANIZATION_ID))[-1][0] == (
        "platform.organization.admin_invited"
    )


async def test_the_listing_pages_by_name_and_filters(app_db: Database, super_admin: Actor) -> None:
    marker = uuid7().hex[-6:]
    for name in ("Alpha", "Beta", "Gamma"):
        await create(app_db, super_admin, name=f"{marker} {name}")

    async def page(after: tuple[str, UUID] | None) -> list[platform.OrganizationListing]:
        async with app_db.tenant(PLATFORM_ORGANIZATION_ID) as session:
            return await platform.list_organizations(
                session, query=marker, status=None, after=after, limit=2
            )

    first = await page(None)
    assert [o.name for o in first] == [f"{marker} Alpha", f"{marker} Beta"]
    second = await page((first[-1].name, first[-1].id))
    assert [o.name for o in second] == [f"{marker} Gamma"]
    async with app_db.tenant(PLATFORM_ORGANIZATION_ID) as session:
        suspended = await platform.list_organizations(
            session, query=marker, status="suspended", after=None, limit=10
        )
    assert suspended == []
