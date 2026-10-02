"""Users and email invitations (PRD §6, §9; ADR-0014).

An invitation is a user in the `invited` status plus SP-02a's single-use `set_password` link,
which activates the account and verifies the address when used. The rules every change obeys:

- **Escalation:** nobody grants a permission they don't hold, by inviting or by assigning roles.
- **Outranked:** nobody changes the roles or status of someone holding permissions they don't.
- **Last admin:** an organisation keeps at least one active holder of its admin role.
- **Self:** nobody disables themselves.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Select, delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access import UNSET, Unset, admin_role_key
from hirevion_core.access.actor import Actor
from hirevion_core.access.audit import record
from hirevion_core.access.errors import Conflict, Invalid, NotFound, Refused
from hirevion_core.identity.grants import load_grants
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.identity.sessions import revoke_all_sessions
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.identity.tokens import issue_token, revoke_tokens
from hirevion_core.mail.sender import queue_mail
from hirevion_core.models import (
    Organization,
    Role,
    RolePermission,
    Team,
    TeamMember,
    User,
    UserRole,
)
from hirevion_core.models.user import ACCESS_SCOPES

LOCALES = ("en-IN", "en-US")
NAME_MAX = 200


@dataclass(frozen=True, slots=True)
class UserFilters:
    status: str | None = None
    role_id: UUID | None = None
    team_id: UUID | None = None
    query: str | None = None
    """Part of a name or email address, any case."""


@dataclass(frozen=True, slots=True)
class UserDetail:
    user: User
    roles: list[Role]
    teams: list[Team]


@dataclass(frozen=True, slots=True)
class Invitation:
    email: str
    name: str
    role_ids: Sequence[UUID]
    team_ids: Sequence[UUID] = ()
    access_scope: str = "organization"
    locale: str = "en-IN"


def _now() -> datetime:
    return datetime.now(UTC)


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


# Reading


def users_statement(filters: UserFilters) -> Select[User]:
    """The organisation's users matching `filters`; the caller orders and pages it."""
    statement = select(User)
    if filters.status is not None:
        statement = statement.where(User.status == filters.status)
    if filters.role_id is not None:
        holders = select(UserRole.user_id).where(UserRole.role_id == filters.role_id)
        statement = statement.where(User.id.in_(holders))
    if filters.team_id is not None:
        members = select(TeamMember.user_id).where(TeamMember.team_id == filters.team_id)
        statement = statement.where(User.id.in_(members))
    if filters.query and filters.query.strip():
        pattern = _like(filters.query.strip())
        statement = statement.where(
            or_(User.name.ilike(pattern, escape="\\"), User.email.ilike(pattern, escape="\\"))
        )
    return statement


async def describe(session: AsyncSession, people: Sequence[User]) -> list[UserDetail]:
    """The users with their roles (system roles first) and teams, in two queries."""
    ids = [person.id for person in people]
    roles: dict[UUID, list[Role]] = {user_id: [] for user_id in ids}
    teams: dict[UUID, list[Team]] = {user_id: [] for user_id in ids}
    if ids:
        for user_id, role in await session.execute(
            select(UserRole.user_id, Role)
            .join(Role, Role.id == UserRole.role_id)
            .where(UserRole.user_id.in_(ids))
            .order_by(Role.system.desc(), Role.name)
        ):
            roles[user_id].append(role)
        for user_id, team in await session.execute(
            select(TeamMember.user_id, Team)
            .join(Team, Team.id == TeamMember.team_id)
            .where(TeamMember.user_id.in_(ids))
            .order_by(Team.name)
        ):
            teams[user_id].append(team)
    return [UserDetail(person, roles[person.id], teams[person.id]) for person in people]


async def _user(session: AsyncSession, user_id: UUID) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise NotFound("user-not-found", "No such user")
    return user


async def get_user(session: AsyncSession, user_id: UUID) -> UserDetail:
    return (await describe(session, [await _user(session, user_id)]))[0]


# Checks


def _name(value: str) -> str:
    name = value.strip()
    if not name or len(name) > NAME_MAX:
        raise Invalid("invalid-name", f"Use 1 to {NAME_MAX} characters", field="name")
    return name


def _access_scope(value: str) -> str:
    if value not in ACCESS_SCOPES:
        raise Invalid("invalid-access-scope", "Unknown access", field="access_scope")
    return value


async def _roles(session: AsyncSession, role_ids: Sequence[UUID]) -> list[Role]:
    if not role_ids:
        raise Invalid("roles-required", "Choose at least one role", field="role_ids")
    wanted = set(role_ids)
    found = list((await session.scalars(select(Role).where(Role.id.in_(wanted)))).all())
    if len(found) != len(wanted):
        raise Invalid("unknown-role", "Choose roles from this organisation", field="role_ids")
    return sorted(found, key=lambda role: (not role.system, role.name))


async def _live_teams(session: AsyncSession, team_ids: Sequence[UUID]) -> list[Team]:
    wanted = set(team_ids)
    if not wanted:
        return []
    found = list(
        (
            await session.scalars(
                select(Team)
                .where(Team.id.in_(wanted), Team.archived_at.is_(None))
                .order_by(Team.name)
            )
        ).all()
    )
    if len(found) != len(wanted):
        raise Invalid(
            "unknown-team", "Choose current teams from this organisation", field="team_ids"
        )
    return found


async def _granted_by(session: AsyncSession, roles: Sequence[Role]) -> set[str]:
    keys = [role.key for role in roles if role.key is not None]
    custom = [role.id for role in roles if role.key is None]
    stored: Sequence[str] = []
    if custom:
        stored = (
            await session.scalars(
                select(RolePermission.permission).where(RolePermission.role_id.in_(custom))
            )
        ).all()
    return set(permissions_for(keys, stored))


def _guard_escalation(actor: Actor, granted: set[str]) -> None:
    missing = sorted(granted - actor.permissions)
    if missing:
        raise Refused(
            "escalation",
            "You can't grant permissions you don't hold",
            detail=", ".join(missing),
        )


async def _guard_outranked(session: AsyncSession, actor: Actor, user_id: UUID) -> None:
    held = set((await load_grants(session, user_id)).permissions)
    if held - actor.permissions:
        raise Refused("outranked", "You can't change someone who holds permissions you don't")


async def _guard_last_admin(session: AsyncSession, user: User) -> None:
    """Refuses when `user` is the organisation's only active holder of its admin role."""
    admins = set(
        (
            await session.scalars(
                select(UserRole.user_id)
                .join(Role, Role.id == UserRole.role_id)
                .join(User, User.id == UserRole.user_id)
                .where(Role.key == admin_role_key(user.organization_id), User.status == "active")
            )
        ).all()
    )
    if admins == {user.id}:
        raise Conflict(
            "last-admin",
            "An organisation needs at least one active admin",
            detail="Make someone else an admin first.",
        )


# Invitations


async def _send_invitation(
    session: AsyncSession, user: User, inviter_name: str, settings: IdentitySettings
) -> None:
    organization = await session.get_one(Organization, user.organization_id)
    hours = settings.set_password_token_hours
    token = await issue_token(
        session,
        organization_id=user.organization_id,
        user_id=user.id,
        purpose="set_password",
        ttl=timedelta(hours=hours),
        now=_now(),
    )
    await queue_mail(
        session,
        organization_id=user.organization_id,
        template="invitation",
        to=user.email,
        locale=user.locale,
        context={
            "name": user.name,
            "inviter": inviter_name,
            "organization": organization.name,
            "link": f"{settings.web_origin.rstrip('/')}/set-password/{token}",
            "hours": str(hours),
        },
    )


async def create_invitation(
    session: AsyncSession,
    actor: Actor,
    organization_id: UUID,
    invitation: Invitation,
    *,
    inviter_name: str,
    settings: IdentitySettings,
) -> UserDetail:
    """Invites someone into `organization_id` (the session's current tenant), without the
    escalation guard: `invite_user` applies it, and the platform invites admins as itself."""
    if invitation.locale not in LOCALES:
        raise Invalid("invalid-locale", "Unsupported language", field="locale")
    roles = await _roles(session, invitation.role_ids)
    teams = await _live_teams(session, invitation.team_ids)
    user = User(
        organization_id=organization_id,
        email=invitation.email.strip().lower(),
        name=_name(invitation.name),
        locale=invitation.locale,
        status="invited",
        access_scope=_access_scope(invitation.access_scope),
    )
    try:
        async with session.begin_nested():
            session.add(user)
    except IntegrityError as error:
        if "uq_users_email" in str(error.orig):
            raise Conflict(
                "email-taken", "This email address already has an account", field="email"
            ) from error
        raise
    session.add_all(
        [UserRole(organization_id=organization_id, user_id=user.id, role_id=r.id) for r in roles]
        + [
            TeamMember(organization_id=organization_id, team_id=t.id, user_id=user.id)
            for t in teams
        ]
    )
    await session.flush()
    await _send_invitation(session, user, inviter_name, settings)
    await record(
        session,
        actor,
        "user.invited",
        "user",
        user.id,
        organization_id=organization_id,
        details={
            "email": user.email,
            "role_ids": [str(role.id) for role in roles],
            "team_ids": [str(team.id) for team in teams],
            "access_scope": user.access_scope,
        },
    )
    return UserDetail(user, roles, teams)


async def _actor_name(session: AsyncSession, actor: Actor) -> str:
    return (await session.get_one(User, actor.user_id)).name


async def invite_user(
    session: AsyncSession, actor: Actor, invitation: Invitation, *, settings: IdentitySettings
) -> UserDetail:
    roles = await _roles(session, invitation.role_ids)
    _guard_escalation(actor, await _granted_by(session, roles))
    return await create_invitation(
        session,
        actor,
        actor.organization_id,
        invitation,
        inviter_name=await _actor_name(session, actor),
        settings=settings,
    )


async def _invited(session: AsyncSession, user_id: UUID) -> User:
    user = await _user(session, user_id)
    if user.status != "invited":
        raise Conflict("not-invited", "Only an invitation can be resent or cancelled")
    return user


async def resend_invitation(
    session: AsyncSession, actor: Actor, user_id: UUID, *, settings: IdentitySettings
) -> None:
    """A new link; the earlier ones stop working."""
    user = await _invited(session, user_id)
    await revoke_tokens(session, user_id=user.id, purpose="set_password", now=_now())
    await _send_invitation(session, user, await _actor_name(session, actor), settings)
    await record(session, actor, "user.invitation.resent", "user", user.id)


async def cancel_invitation(session: AsyncSession, actor: Actor, user_id: UUID) -> None:
    """Deletes the invited user (and their roles, teams and links), freeing the address."""
    user = await _invited(session, user_id)
    await _guard_outranked(session, actor, user.id)
    email = user.email
    await session.delete(user)
    await session.flush()
    await record(
        session, actor, "user.invitation.cancelled", "user", user_id, details={"email": email}
    )


# Changing users


async def update_user(
    session: AsyncSession,
    actor: Actor,
    user_id: UUID,
    *,
    name: str | Unset = UNSET,
    access_scope: str | Unset = UNSET,
    team_ids: Sequence[UUID] | Unset = UNSET,
) -> UserDetail:
    """Changes a user's name, access and teams. `team_ids` replaces their current teams;
    memberships of archived teams stay as history."""
    user = await _user(session, user_id)
    changed: list[str] = []
    details: dict[str, object] = {}
    if not isinstance(name, Unset) and _name(name) != user.name:
        user.name = _name(name)
        changed.append("name")
    if not isinstance(access_scope, Unset) and _access_scope(access_scope) != user.access_scope:
        user.access_scope = access_scope
        changed.append("access_scope")
    if not isinstance(team_ids, Unset):
        wanted = {team.id for team in await _live_teams(session, team_ids)}
        current = set(
            (
                await session.scalars(
                    select(TeamMember.team_id)
                    .join(Team, Team.id == TeamMember.team_id)
                    .where(TeamMember.user_id == user.id, Team.archived_at.is_(None))
                )
            ).all()
        )
        if wanted != current:
            if current - wanted:
                await session.execute(
                    delete(TeamMember).where(
                        TeamMember.user_id == user.id, TeamMember.team_id.in_(current - wanted)
                    )
                )
            session.add_all(
                TeamMember(organization_id=user.organization_id, team_id=team_id, user_id=user.id)
                for team_id in wanted - current
            )
            changed.append("team_ids")
            details["teams"] = {
                "before": sorted(map(str, current)),
                "after": sorted(map(str, wanted)),
            }
    if changed:
        await session.flush()
        await record(
            session,
            actor,
            "user.updated",
            "user",
            user.id,
            details={"fields": sorted(changed), **details},
        )
    return await get_user(session, user.id)


async def set_roles(
    session: AsyncSession, actor: Actor, user_id: UUID, role_ids: Sequence[UUID]
) -> UserDetail:
    """Replaces a user's roles ("Permissions changed", PRD §97)."""
    user = await _user(session, user_id)
    roles = await _roles(session, role_ids)
    await _guard_outranked(session, actor, user.id)
    _guard_escalation(actor, await _granted_by(session, roles))
    before = (await get_user(session, user.id)).roles
    admin = admin_role_key(user.organization_id)
    if (
        user.status == "active"
        and any(role.key == admin for role in before)
        and not any(role.key == admin for role in roles)
    ):
        await _guard_last_admin(session, user)
    if {role.id for role in before} != {role.id for role in roles}:
        await session.execute(delete(UserRole).where(UserRole.user_id == user.id))
        session.add_all(
            UserRole(organization_id=user.organization_id, user_id=user.id, role_id=role.id)
            for role in roles
        )
        await session.flush()
        await record(
            session,
            actor,
            "user.roles.changed",
            "user",
            user.id,
            details={
                "before": [{"id": str(r.id), "name": r.name} for r in before],
                "after": [{"id": str(r.id), "name": r.name} for r in roles],
            },
        )
    return await get_user(session, user.id)


async def disable_user(session: AsyncSession, actor: Actor, user_id: UUID) -> UserDetail:
    """Stops a user signing in: every session ends and every emailed link stops working."""
    user = await _user(session, user_id)
    if user.id == actor.user_id:
        raise Conflict("self-disable", "You can't disable your own account")
    await _guard_outranked(session, actor, user.id)
    if user.status != "disabled":
        await _guard_last_admin(session, user)
        now = _now()
        user.status = "disabled"
        await revoke_all_sessions(session, user_id=user.id, except_session=None, now=now)
        await revoke_tokens(session, user_id=user.id, now=now)
        await session.flush()
        await record(session, actor, "user.disabled", "user", user.id)
    return await get_user(session, user.id)


async def enable_user(session: AsyncSession, actor: Actor, user_id: UUID) -> UserDetail:
    """Lets a disabled user back in: active if they have a password, invited otherwise."""
    user = await _user(session, user_id)
    await _guard_outranked(session, actor, user.id)
    if user.status == "disabled":
        user.status = "active" if user.password_hash else "invited"
        await session.flush()
        await record(session, actor, "user.enabled", "user", user.id)
    return await get_user(session, user.id)
