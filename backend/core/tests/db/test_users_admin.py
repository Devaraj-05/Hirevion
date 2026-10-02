"""User administration and email invitations (plan Task 7, ADR-0014)."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.access import structure, users
from hirevion_core.access.actor import Actor
from hirevion_core.access.errors import Conflict, Invalid, Refused
from hirevion_core.access.users import Invitation, UserFilters
from hirevion_core.db.session import Database
from hirevion_core.identity.passwords import PasswordPolicy, hash_password
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.identity.service import AuthService, LoginOk
from hirevion_core.identity.sessions import resolve_session
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.ids import uuid7

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]
SETTINGS = IdentitySettings(web_origin="https://app.hirevion.localhost")
PASSWORD = "correct horse battery staple"  # noqa: S105 (a test input)
WHERE = {"ip": "203.0.113.7", "user_agent": "Test browser"}


class NoBreaches:
    async def is_breached(self, password: str) -> bool:
        return False


def email() -> str:
    return f"invitee-{uuid7().hex[-12:]}@acme.example.test"


async def role_id(engine: AsyncEngine, organization_id: UUID, key: str) -> UUID:
    async with engine.connect() as conn:
        found = await conn.scalar(
            text("SELECT id FROM roles WHERE organization_id = :org AND key = :key"),
            {"org": organization_id, "key": key},
        )
    assert isinstance(found, UUID)
    return found


async def custom_role(
    engine: AsyncEngine, organization_id: UUID, name: str, permissions: list[str]
) -> UUID:
    new_id = uuid7()
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO roles (id, organization_id, name) VALUES (:id, :org, :name)"),
            {"id": new_id, "org": organization_id, "name": name},
        )
        for permission in permissions:
            await conn.execute(
                text(
                    "INSERT INTO role_permissions (organization_id, role_id, permission) "
                    "VALUES (:org, :role, :permission)"
                ),
                {"org": organization_id, "role": new_id, "permission": permission},
            )
    return new_id


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


async def last_audit(engine: AsyncEngine, organization_id: UUID) -> tuple[str, dict[str, Any]]:
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT action, details FROM audit_logs WHERE organization_id = :org "
                    "ORDER BY seq DESC LIMIT 1"
                ),
                {"org": organization_id},
            )
        ).one()
    return row.action, row.details


def token_of(mail: dict[str, Any]) -> str:
    return str(mail["context"]["link"]).rsplit("/", 1)[1]


@pytest.fixture
def auth(app_db: Database, valkey: Redis) -> AuthService:
    return AuthService(app_db, valkey, policy=PasswordPolicy(NoBreaches()), settings=SETTINGS)


@pytest.fixture
async def acme(make_organization: MakeOrganization, make_user) -> Actor:
    organization = await make_organization("Acme")
    admin = await make_user(organization, name="Olivia Admin", roles=["org_admin"])
    return Actor(admin, organization, frozenset(permissions_for(["org_admin"])))


async def invite(
    app_db: Database, actor: Actor, address: str, role_ids: list[UUID], **extra: Any
) -> users.UserDetail:
    async with app_db.tenant(actor.organization_id) as session:
        return await users.invite_user(
            session,
            actor,
            Invitation(email=address, name="Asha Rao", role_ids=role_ids, **extra),
            settings=SETTINGS,
        )


# Invitations


async def test_an_invitation_creates_an_invited_user_and_emails_the_link(
    app_db: Database, admin_engine: AsyncEngine, acme: Actor, auth: AuthService
) -> None:
    recruiter = await role_id(admin_engine, acme.organization_id, "recruiter")
    async with app_db.tenant(acme.organization_id) as session:
        team = await structure.create_team(session, acme, "Platform hiring", None, None)
    address = email()
    invited = await invite(
        app_db, acme, f"  {address.upper()} ", [recruiter], team_ids=[team.id], access_scope="teams"
    )

    assert (invited.user.email, invited.user.status, invited.user.access_scope) == (
        address,
        "invited",
        "teams",
    )
    assert [r.key for r in invited.roles] == ["recruiter"]
    assert [t.name for t in invited.teams] == ["Platform hiring"]
    [mail] = await mails_to(admin_engine, address)
    assert mail["template"] == "invitation"
    assert mail["context"]["inviter"] == "Olivia Admin"
    assert mail["context"]["organization"] == "Acme"
    action, details = await last_audit(admin_engine, acme.organization_id)
    assert action == "user.invited"
    assert "link" not in str(details) and token_of(mail) not in str(details)

    # Accepting is SP-02a's set-password link: the user becomes active and can sign in.
    assert await auth.set_password(token_of(mail), "a long enough first password", **WHERE) is None
    assert isinstance(await auth.login(address, "a long enough first password", **WHERE), LoginOk)


async def test_a_resend_replaces_the_earlier_link(
    app_db: Database, admin_engine: AsyncEngine, acme: Actor, auth: AuthService
) -> None:
    address = email()
    invited = await invite(
        app_db, acme, address, [await role_id(admin_engine, acme.organization_id, "recruiter")]
    )
    async with app_db.tenant(acme.organization_id) as session:
        await users.resend_invitation(session, acme, invited.user.id, settings=SETTINGS)
    first, second = await mails_to(admin_engine, address)
    assert await auth.set_password(token_of(first), "a long enough password", **WHERE) == [
        "invalid_token"
    ]
    assert await auth.set_password(token_of(second), "a long enough password", **WHERE) is None
    assert (await last_audit(admin_engine, acme.organization_id))[0] == "auth.account.activated"


async def test_a_cancelled_invitation_frees_the_address(
    app_db: Database, admin_engine: AsyncEngine, acme: Actor
) -> None:
    recruiter = await role_id(admin_engine, acme.organization_id, "recruiter")
    address = email()
    invited = await invite(app_db, acme, address, [recruiter])
    async with app_db.tenant(acme.organization_id) as session:
        await users.cancel_invitation(session, acme, invited.user.id)
    assert (await last_audit(admin_engine, acme.organization_id))[0] == (
        "user.invitation.cancelled"
    )
    again = await invite(app_db, acme, address, [recruiter])
    assert again.user.id != invited.user.id


async def test_only_invitations_can_be_resent_or_cancelled(app_db: Database, acme: Actor) -> None:
    for action in (
        lambda s: users.resend_invitation(s, acme, acme.user_id, settings=SETTINGS),
        lambda s: users.cancel_invitation(s, acme, acme.user_id),
    ):
        with pytest.raises(Conflict) as refusal:
            async with app_db.tenant(acme.organization_id) as session:
                await action(session)
        assert refusal.value.code == "not-invited"


async def test_an_address_in_use_anywhere_is_refused_without_saying_where(
    app_db: Database,
    admin_engine: AsyncEngine,
    acme: Actor,
    make_organization: MakeOrganization,
    make_user,
) -> None:
    globex = await make_organization("Globex")
    address = email()
    await make_user(globex, email=address)
    with pytest.raises(Conflict) as refusal:
        await invite(
            app_db, acme, address, [await role_id(admin_engine, acme.organization_id, "recruiter")]
        )
    assert (refusal.value.code, refusal.value.field, refusal.value.detail) == (
        "email-taken",
        "email",
        None,
    )


async def test_an_invitation_needs_a_role(app_db: Database, acme: Actor) -> None:
    with pytest.raises(Invalid) as refusal:
        await invite(app_db, acme, email(), [])
    assert (refusal.value.code, refusal.value.field) == ("roles-required", "role_ids")


async def test_nobody_grants_what_they_do_not_hold(
    app_db: Database, admin_engine: AsyncEngine, acme: Actor, make_user
) -> None:
    manager_role = await custom_role(
        admin_engine, acme.organization_id, "User manager", ["admin.users.manage"]
    )
    manager = Actor(
        await make_user(acme.organization_id),
        acme.organization_id,
        frozenset(permissions_for([], ["admin.users.manage"])),
    )
    org_admin = await role_id(admin_engine, acme.organization_id, "org_admin")
    with pytest.raises(Refused) as refusal:
        await invite(app_db, manager, email(), [org_admin])
    assert refusal.value.code == "escalation"
    # A role within their own permissions is fine.
    invited = await invite(app_db, manager, email(), [manager_role])
    assert [r.name for r in invited.roles] == ["User manager"]


# Changing users


async def test_roles_change_with_before_and_after_in_the_audit(
    app_db: Database, admin_engine: AsyncEngine, acme: Actor, make_user
) -> None:
    asha = await make_user(acme.organization_id, roles=["recruiter"])
    manager = await role_id(admin_engine, acme.organization_id, "hiring_manager")
    async with app_db.tenant(acme.organization_id) as session:
        changed = await users.set_roles(session, acme, asha, [manager])
    assert [r.key for r in changed.roles] == ["hiring_manager"]
    action, details = await last_audit(admin_engine, acme.organization_id)
    assert action == "user.roles.changed"
    assert [r["name"] for r in details["before"]] == ["Recruiter"]
    assert [r["name"] for r in details["after"]] == ["Hiring manager"]


async def test_the_last_admin_keeps_their_role_and_stays_enabled(
    app_db: Database, admin_engine: AsyncEngine, acme: Actor, make_user
) -> None:
    recruiter = await role_id(admin_engine, acme.organization_id, "recruiter")
    other = Actor(
        await make_user(acme.organization_id, roles=["org_admin"]),
        acme.organization_id,
        acme.permissions,
    )
    # Two admins: one may step down.
    async with app_db.tenant(acme.organization_id) as session:
        await users.set_roles(session, other, other.user_id, [recruiter])
    for change in (
        lambda s: users.set_roles(s, other, acme.user_id, [recruiter]),
        lambda s: users.disable_user(s, other, acme.user_id),
    ):
        with pytest.raises(Conflict) as refusal:
            async with app_db.tenant(acme.organization_id) as session:
                await change(session)
        assert refusal.value.code == "last-admin"


async def test_nobody_disables_themselves(app_db: Database, acme: Actor, make_user) -> None:
    await make_user(acme.organization_id, roles=["org_admin"])
    with pytest.raises(Conflict) as refusal:
        async with app_db.tenant(acme.organization_id) as session:
            await users.disable_user(session, acme, acme.user_id)
    assert refusal.value.code == "self-disable"


async def test_nobody_changes_someone_who_outranks_them(
    app_db: Database, admin_engine: AsyncEngine, acme: Actor, make_user
) -> None:
    manager = Actor(
        await make_user(acme.organization_id),
        acme.organization_id,
        frozenset(permissions_for(["recruiter"], ["admin.users.manage"])),
    )
    recruiter = await role_id(admin_engine, acme.organization_id, "recruiter")
    with pytest.raises(Refused) as refusal:
        async with app_db.tenant(acme.organization_id) as session:
            await users.set_roles(session, manager, acme.user_id, [recruiter])
    assert refusal.value.code == "outranked"


async def test_disabling_ends_sessions_and_enabling_restores_the_status(
    app_db: Database, acme: Actor, auth: AuthService, make_user
) -> None:
    address = email()
    asha = await make_user(
        acme.organization_id,
        email=address,
        password_hash=hash_password(PASSWORD),
        roles=["recruiter"],
    )
    signed = await auth.login(address, PASSWORD, **WHERE)
    assert isinstance(signed, LoginOk)

    async with app_db.tenant(acme.organization_id) as session:
        disabled = await users.disable_user(session, acme, asha)
    assert disabled.user.status == "disabled"
    now = datetime.now(UTC)
    assert await resolve_session(app_db, signed.session_token, settings=SETTINGS, now=now) is None

    async with app_db.tenant(acme.organization_id) as session:
        enabled = await users.enable_user(session, acme, asha)
    assert enabled.user.status == "active"


async def test_updating_teams_and_scope(
    app_db: Database, admin_engine: AsyncEngine, acme: Actor, make_user
) -> None:
    asha = await make_user(acme.organization_id, roles=["recruiter"])
    async with app_db.tenant(acme.organization_id) as session:
        team = await structure.create_team(session, acme, "Campus", None, None)
        old = await structure.create_team(session, acme, "Old", None, None)
        await structure.update_team(session, acme, old.id, archived=True)
    async with app_db.tenant(acme.organization_id) as session:
        updated = await users.update_user(
            session, acme, asha, name="Asha R.", access_scope="teams", team_ids=[team.id]
        )
    assert (updated.user.name, updated.user.access_scope) == ("Asha R.", "teams")
    assert [t.name for t in updated.teams] == ["Campus"]
    action, details = await last_audit(admin_engine, acme.organization_id)
    assert action == "user.updated"
    assert details["fields"] == ["access_scope", "name", "team_ids"]

    with pytest.raises(Invalid) as refusal:
        async with app_db.tenant(acme.organization_id) as session:
            await users.update_user(session, acme, asha, team_ids=[old.id])
    assert refusal.value.field == "team_ids"


# Listing


async def test_listing_filters_by_status_role_team_and_text(
    app_db: Database, admin_engine: AsyncEngine, acme: Actor, make_user
) -> None:
    await make_user(acme.organization_id, name="Ravi Kumar", roles=["recruiter"])
    await make_user(acme.organization_id, name="Hema Iyer", roles=["hiring_manager"])
    await make_user(acme.organization_id, name="Ishan Old", status="disabled")
    recruiter = await role_id(admin_engine, acme.organization_id, "recruiter")

    async def names(filters: UserFilters) -> list[str]:
        async with app_db.tenant(acme.organization_id) as session:
            listed = (await session.scalars(users.users_statement(filters))).all()
            return sorted(u.name for u in listed)

    assert await names(UserFilters()) == ["Hema Iyer", "Ishan Old", "Olivia Admin", "Ravi Kumar"]
    assert await names(UserFilters(status="disabled")) == ["Ishan Old"]
    assert await names(UserFilters(role_id=recruiter)) == ["Ravi Kumar"]
    assert await names(UserFilters(query="iyer")) == ["Hema Iyer"]
