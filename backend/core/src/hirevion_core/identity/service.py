"""Sign-in, sessions, passwords and email changes (SP-02 spec; ADR-0013).

Answers never reveal whether an account exists: an unknown email gets the same refusal (after
the same argon2id work) as a wrong password, counts towards the same lockout, and a password
reset for it returns normally without sending anything. Every action on a known account is
audited in its organisation's chain.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import Row, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.audit import AuditEntry, AuditService
from hirevion_core.db.session import Database
from hirevion_core.identity import PLATFORM_ORGANIZATION_ID
from hirevion_core.identity.grants import load_grants
from hirevion_core.identity.lockout import Lockout
from hirevion_core.identity.passwords import (
    PasswordPolicy,
    PasswordProblem,
    hash_password_in_thread,
    verify_password_in_thread,
)
from hirevion_core.identity.sessions import (
    SessionContext,
    create_session,
    list_sessions,
    mark_stepped_up,
    revoke_all_sessions,
    revoke_session,
)
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.identity.tokens import TokenPurpose, claim_token, issue_token, lookup_token
from hirevion_core.mail.render import MailTemplate
from hirevion_core.mail.sender import queue_mail
from hirevion_core.models import Organization, User

PasswordOutcome = PasswordProblem | Literal["wrong_current", "invalid_token"]
EmailChangeOutcome = Literal["ok", "wrong_password", "unavailable"]


@dataclass(frozen=True, slots=True)
class LoginOk:
    session_token: str
    csrf_token: str
    context: SessionContext


@dataclass(frozen=True, slots=True)
class LoginRefused:
    """Wrong email or password, or an account that can't sign in. `retry_after` is set while
    the email is locked out."""

    retry_after: int | None


@dataclass(frozen=True, slots=True)
class UserView:
    id: UUID
    name: str
    email: str


@dataclass(frozen=True, slots=True)
class OrganizationView:
    id: UUID
    name: str


@dataclass(frozen=True, slots=True)
class SessionView:
    """ADR-0012's session contract: `organization` is None for the Platform's super admins."""

    user: UserView
    organization: OrganizationView | None
    roles: list[str]
    custom_roles: list[str]
    permissions: list[str]


@dataclass(frozen=True, slots=True)
class SessionSummary:
    id: UUID
    created_at: datetime
    last_seen_at: datetime
    ip: str | None
    user_agent: str | None
    current: bool


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AuthService:
    def __init__(
        self,
        db: Database,
        redis: Redis,
        *,
        policy: PasswordPolicy,
        settings: IdentitySettings,
        audit: AuditService | None = None,
        lockout: Lockout | None = None,
    ) -> None:
        self._db = db
        self._policy = policy
        self._settings = settings
        self._audit = audit or AuditService()
        self._lockout = lockout or Lockout(redis, settings=settings)

    # Sign-in and sign-out

    async def login(
        self, email: str, password: str, *, ip: str | None, user_agent: str | None
    ) -> LoginOk | LoginRefused:
        email = email.strip()
        locked = await self._lockout.retry_after(email)
        if locked is not None:
            # No password check while locked: the answer must not reveal whether it was right.
            return LoginRefused(locked)

        row = await self._find_user(email)
        valid, needs_rehash = await verify_password_in_thread(
            row.password_hash if row else None, password
        )
        if (
            row is None
            or not valid
            or row.status != "active"
            or row.organization_status != "active"
        ):
            wait = await self._lockout.record_failure(email)
            if row is not None:
                async with self._db.tenant(row.organization_id) as session:
                    await self._record(
                        session,
                        row.organization_id,
                        row.user_id,
                        "auth.login.failed",
                        ip,
                        user_agent,
                    )
                    if wait is not None:
                        await self._record(
                            session,
                            row.organization_id,
                            row.user_id,
                            "auth.lockout.started",
                            ip,
                            user_agent,
                        )
            return LoginRefused(wait)

        await self._lockout.reset(email)
        now = _utcnow()
        async with self._db.tenant(row.organization_id) as session:
            if needs_rehash:
                await session.execute(
                    update(User)
                    .where(User.id == row.user_id)
                    .values(password_hash=await hash_password_in_thread(password))
                )
            token, csrf, web_session = await create_session(
                session,
                user_id=row.user_id,
                organization_id=row.organization_id,
                ip=ip,
                user_agent=user_agent,
                settings=self._settings,
                now=now,
            )
            await self._record(
                session, row.organization_id, row.user_id, "auth.login.succeeded", ip, user_agent
            )
        context = SessionContext(
            web_session.id, row.user_id, row.organization_id, web_session.csrf_hash
        )
        return LoginOk(token, csrf, context)

    async def logout(
        self, context: SessionContext, *, ip: str | None, user_agent: str | None
    ) -> None:
        async with self._db.tenant(context.organization_id) as session:
            await revoke_session(
                session, user_id=context.user_id, session_id=context.session_id, now=_utcnow()
            )
            await self._record(
                session, context.organization_id, context.user_id, "auth.logout", ip, user_agent
            )

    # Sessions

    async def session_view(self, context: SessionContext) -> SessionView:
        async with self._db.tenant(context.organization_id) as session:
            user = await session.get_one(User, context.user_id)
            organization = await session.get_one(Organization, context.organization_id)
            grants = await load_grants(session, context.user_id)
        return SessionView(
            user=UserView(user.id, user.name, user.email),
            organization=None
            if organization.id == PLATFORM_ORGANIZATION_ID
            else OrganizationView(organization.id, organization.name),
            roles=grants.role_keys,
            custom_roles=grants.custom_roles,
            permissions=grants.permissions,
        )

    async def list_sessions(self, context: SessionContext) -> list[SessionSummary]:
        async with self._db.tenant(context.organization_id) as session:
            rows = await list_sessions(
                session, user_id=context.user_id, settings=self._settings, now=_utcnow()
            )
        return [
            SessionSummary(
                id=row.id,
                created_at=row.created_at,
                last_seen_at=row.last_seen_at,
                ip=str(row.ip) if row.ip is not None else None,
                user_agent=row.user_agent,
                current=row.id == context.session_id,
            )
            for row in rows
        ]

    async def revoke_session(
        self,
        context: SessionContext,
        session_id: UUID,
        *,
        ip: str | None,
        user_agent: str | None,
    ) -> bool:
        async with self._db.tenant(context.organization_id) as session:
            ended = await revoke_session(
                session, user_id=context.user_id, session_id=session_id, now=_utcnow()
            )
            if ended:
                await self._record(
                    session,
                    context.organization_id,
                    context.user_id,
                    "auth.session.revoked",
                    ip,
                    user_agent,
                    {"session_id": str(session_id)},
                )
        return ended

    async def revoke_other_sessions(
        self, context: SessionContext, *, ip: str | None, user_agent: str | None
    ) -> int:
        async with self._db.tenant(context.organization_id) as session:
            ended = await revoke_all_sessions(
                session,
                user_id=context.user_id,
                except_session=context.session_id,
                now=_utcnow(),
            )
            if ended:
                await self._record(
                    session,
                    context.organization_id,
                    context.user_id,
                    "auth.session.revoked",
                    ip,
                    user_agent,
                    {"count": ended},
                )
        return ended

    # Passwords

    async def change_password(
        self,
        context: SessionContext,
        current: str,
        new: str,
        *,
        ip: str | None,
        user_agent: str | None,
    ) -> list[PasswordOutcome] | None:
        user, organization_name = await self._user_and_organization(
            context.organization_id, context.user_id
        )
        if not (await verify_password_in_thread(user.password_hash, current))[0]:
            return ["wrong_current"]
        problems = await self._policy.check(
            new, email=user.email, name=user.name, organization=organization_name
        )
        if problems:
            return list(problems)
        now = _utcnow()
        async with self._db.tenant(context.organization_id) as session:
            await self._set_password(session, user.id, new, now)
            await revoke_all_sessions(
                session, user_id=user.id, except_session=context.session_id, now=now
            )
            await self._record(
                session, context.organization_id, user.id, "auth.password.changed", ip, user_agent
            )
            await self._mail(
                session,
                user,
                "password_changed",
                user.email,
                {"forgot_link": self._link("/forgot-password")},
            )
        return None

    # Step-up

    async def step_up(
        self, context: SessionContext, password: str, *, ip: str | None, user_agent: str | None
    ) -> Literal["ok", "wrong_password"] | LoginRefused:
        """Confirms the password before a sensitive change (ADR-0014). Wrong passwords count
        towards the sign-in lockout, so a stolen session can't be used to guess the password."""
        user, _ = await self._user_and_organization(context.organization_id, context.user_id)
        locked = await self._lockout.retry_after(user.email)
        if locked is not None:
            return LoginRefused(locked)
        if not (await verify_password_in_thread(user.password_hash, password))[0]:
            wait = await self._lockout.record_failure(user.email)
            async with self._db.tenant(context.organization_id) as session:
                await self._record(
                    session, user.organization_id, user.id, "auth.step_up.failed", ip, user_agent
                )
                if wait is not None:
                    await self._record(
                        session,
                        user.organization_id,
                        user.id,
                        "auth.lockout.started",
                        ip,
                        user_agent,
                    )
            return "wrong_password" if wait is None else LoginRefused(wait)

        await self._lockout.reset(user.email)
        async with self._db.tenant(context.organization_id) as session:
            await mark_stepped_up(session, session_id=context.session_id, now=_utcnow())
            await self._record(
                session, user.organization_id, user.id, "auth.step_up.succeeded", ip, user_agent
            )
        return "ok"

    async def request_reset(self, email: str, *, ip: str | None, user_agent: str | None) -> None:
        """Emails a reset link to an active account. Returns the same way when there's none."""
        row = await self._find_user(email.strip())
        if row is None or row.status != "active" or row.organization_status != "active":
            return
        async with self._db.tenant(row.organization_id) as session:
            user = await session.get_one(User, row.user_id)
            minutes = self._settings.reset_token_minutes
            token = await self._issue(session, user, "reset_password", timedelta(minutes=minutes))
            await self._mail(
                session,
                user,
                "reset_password",
                user.email,
                {"link": self._link(f"/reset-password/{token}"), "minutes": str(minutes)},
            )
            await self._record(
                session,
                row.organization_id,
                user.id,
                "auth.password.reset_requested",
                ip,
                user_agent,
            )

    async def reset_password(
        self, token: str, new: str, *, ip: str | None, user_agent: str | None
    ) -> list[PasswordOutcome] | None:
        """Sets a new password from a reset link and ends every session."""
        return await self._password_from_token(token, "reset_password", new, ip, user_agent)

    async def set_password(
        self, token: str, new: str, *, ip: str | None, user_agent: str | None
    ) -> list[PasswordOutcome] | None:
        """An invited user's first password: it activates the account."""
        return await self._password_from_token(token, "set_password", new, ip, user_agent)

    async def _password_from_token(
        self,
        token: str,
        purpose: TokenPurpose,
        new: str,
        ip: str | None,
        user_agent: str | None,
    ) -> list[PasswordOutcome] | None:
        now = _utcnow()
        ref = await lookup_token(self._db, token, purpose, now=now)
        if ref is None:
            return ["invalid_token"]
        user, organization_name = await self._user_and_organization(
            ref.organization_id, ref.user_id
        )
        problems = await self._policy.check(
            new, email=user.email, name=user.name, organization=organization_name
        )
        if problems:
            # The link stays usable: it is claimed only when the password is accepted.
            return list(problems)
        async with self._db.tenant(ref.organization_id) as session:
            if await claim_token(session, ref, now=now) is None:
                return ["invalid_token"]
            await self._set_password(session, user.id, new, now)
            values: dict[str, object] = {}
            if user.email_verified_at is None:
                values["email_verified_at"] = now
            if purpose == "set_password" and user.status == "invited":
                values["status"] = "active"
            if values:
                await session.execute(update(User).where(User.id == user.id).values(**values))
            await revoke_all_sessions(session, user_id=user.id, except_session=None, now=now)
            if purpose == "reset_password":
                await self._record(
                    session, ref.organization_id, user.id, "auth.password.reset", ip, user_agent
                )
                await self._mail(
                    session,
                    user,
                    "password_changed",
                    user.email,
                    {"forgot_link": self._link("/forgot-password")},
                )
            else:
                await self._record(
                    session, ref.organization_id, user.id, "auth.account.activated", ip, user_agent
                )
        await self._lockout.reset(user.email)
        return None

    # Email address

    async def request_email_change(
        self,
        context: SessionContext,
        new_email: str,
        password: str,
        *,
        ip: str | None,
        user_agent: str | None,
    ) -> EmailChangeOutcome:
        """Sends a confirmation link to the new address and a notice to the old one. An address
        already in use answers `unavailable`, which the API reports exactly like `ok`."""
        new_email = new_email.strip()
        user, _ = await self._user_and_organization(context.organization_id, context.user_id)
        if not (await verify_password_in_thread(user.password_hash, password))[0]:
            return "wrong_password"
        if new_email.casefold() == user.email.casefold():
            return "ok"
        if await self._find_user(new_email) is not None:
            return "unavailable"
        async with self._db.tenant(context.organization_id) as session:
            hours = self._settings.verify_token_hours
            token = await self._issue(
                session, user, "verify_email", timedelta(hours=hours), new_email=new_email
            )
            await self._mail(
                session,
                user,
                "verify_email",
                new_email,
                {"link": self._link(f"/verify-email/{token}"), "hours": str(hours)},
            )
            await self._mail(
                session,
                user,
                "email_change_requested",
                user.email,
                {"new_email": new_email, "forgot_link": self._link("/forgot-password")},
            )
            await self._record(
                session,
                context.organization_id,
                user.id,
                "auth.email.change_requested",
                ip,
                user_agent,
            )
        return "ok"

    async def verify_email(self, token: str, *, ip: str | None, user_agent: str | None) -> bool:
        now = _utcnow()
        ref = await lookup_token(self._db, token, "verify_email", now=now)
        if ref is None or ref.new_email is None:
            return False
        try:
            async with self._db.tenant(ref.organization_id) as session:
                if await claim_token(session, ref, now=now) is None:
                    return False
                await session.execute(
                    update(User)
                    .where(User.id == ref.user_id)
                    .values(email=ref.new_email, email_verified_at=now)
                )
                await self._record(
                    session, ref.organization_id, ref.user_id, "auth.email.verified", ip, user_agent
                )
        except IntegrityError:
            # Someone else took the address since the link was sent.
            return False
        return True

    # Helpers

    async def _find_user(self, email: str) -> Row[Any] | None:
        """The sign-in lookup (`auth_user_by_email`): found without a tenant."""
        async with self._db.unscoped() as session:
            return (
                await session.execute(
                    text("SELECT * FROM auth_user_by_email(:email)"), {"email": email}
                )
            ).first()

    async def _user_and_organization(
        self, organization_id: UUID, user_id: UUID
    ) -> tuple[User, str]:
        async with self._db.tenant(organization_id) as session:
            user = await session.get_one(User, user_id)
            organization = await session.get_one(Organization, organization_id)
            return user, organization.name

    async def _set_password(
        self, session: AsyncSession, user_id: UUID, password: str, now: datetime
    ) -> None:
        await session.execute(
            update(User)
            .where(User.id == user_id)
            .values(password_hash=await hash_password_in_thread(password), password_changed_at=now)
        )

    async def _issue(
        self,
        session: AsyncSession,
        user: User,
        purpose: TokenPurpose,
        ttl: timedelta,
        new_email: str | None = None,
    ) -> str:
        return await issue_token(
            session,
            organization_id=user.organization_id,
            user_id=user.id,
            purpose=purpose,
            ttl=ttl,
            now=_utcnow(),
            new_email=new_email,
        )

    async def _mail(
        self,
        session: AsyncSession,
        user: User,
        template: MailTemplate,
        to: str,
        context: dict[str, str],
    ) -> None:
        await queue_mail(
            session,
            organization_id=user.organization_id,
            template=template,
            to=to,
            locale=user.locale,
            context={"name": user.name, **context},
        )

    def _link(self, path: str) -> str:
        return f"{self._settings.web_origin.rstrip('/')}{path}"

    async def _record(
        self,
        session: AsyncSession,
        organization_id: UUID,
        user_id: UUID,
        action: str,
        ip: str | None,
        user_agent: str | None,
        details: dict[str, object] | None = None,
    ) -> None:
        await self._audit.append(
            session,
            organization_id,
            AuditEntry(
                action=action,
                resource_type="user",
                resource_id=str(user_id),
                actor_type="user",
                actor_id=str(user_id),
                ip=ip,
                user_agent=user_agent,
                details=details or {},
            ),
        )


__all__ = [
    "AuthService",
    "EmailChangeOutcome",
    "LoginOk",
    "LoginRefused",
    "OrganizationView",
    "PasswordOutcome",
    "SessionSummary",
    "SessionView",
    "UserView",
]
