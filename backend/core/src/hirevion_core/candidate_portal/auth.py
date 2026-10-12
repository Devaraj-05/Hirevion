"""Candidate sign-in on the portal (master plan §6.3; ADR-0022).

ADR-0013's rules, for candidate accounts: an unknown email gets the same refusal (after the same
argon2id work) as a wrong password; a forgotten-password request answers the same either way;
a locked account isn't told whether its password was right. The lockout is the desktop's
(`candidate:<email>`), so the portal and the app share one budget. Passwords need 12 characters
(ADR-0020): the desktop's device key and new-device code are a second factor.

The invitation's link sets the first password and proves the email address. A reset ends every
portal session and every desktop sign-in of the account.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.audit import AuditEntry, AuditService
from hirevion_core.candidate_access.accounts import (
    AccountRow,
    CandidateTokenPurpose,
    candidate_lockout_key,
    claim_candidate_token,
    find_accounts,
    issue_candidate_token,
    lookup_candidate_token,
)
from hirevion_core.candidate_access.service import evaluate
from hirevion_core.candidate_portal.sessions import (
    PortalSession,
    create_portal_session,
    revoke_portal_sessions,
)
from hirevion_core.db.session import Database
from hirevion_core.identity.lockout import Lockout
from hirevion_core.identity.passwords import (
    PasswordPolicy,
    hash_password_in_thread,
    verify_password_in_thread,
)
from hirevion_core.identity.service import LoginRefused, PasswordOutcome
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.mail.sender import queue_mail
from hirevion_core.models import CandidateAccount, CandidateRefreshToken, Organization

_audit = AuditService()


@dataclass(frozen=True, slots=True)
class PortalLoginOk:
    session_token: str
    csrf_token: str
    context: PortalSession


@dataclass(frozen=True, slots=True)
class PortalView:
    """Who is signed in to the portal, and their organisation's support contact (PRD §25)."""

    account_id: UUID
    name: str
    email: str
    locale: str
    organization_id: UUID
    organization_name: str
    support_email: str


def _now() -> datetime:
    return datetime.now(UTC)


class PortalAuthService:
    def __init__(
        self,
        db: Database,
        redis: Redis,
        *,
        policy: PasswordPolicy,
        settings: IdentitySettings,
        lockout: Lockout | None = None,
    ) -> None:
        self._db = db
        self._policy = policy
        self._settings = settings
        self._lockout = lockout or Lockout(redis, settings=settings)

    # Sign-in and sign-out

    async def login(
        self, email: str, password: str, *, ip: str | None, user_agent: str | None
    ) -> PortalLoginOk | LoginRefused:
        email = email.strip()
        key = candidate_lockout_key(email)
        locked = await self._lockout.retry_after(key)
        if locked is not None:
            return LoginRefused(locked)
        rows = await find_accounts(self._db, email)
        matches: list[AccountRow] = []
        # Every account costs one verification; no accounts cost one against the dummy hash.
        candidates: list[AccountRow | None] = list(rows) or [None]
        for row in candidates:
            valid, _ = await verify_password_in_thread(row.password_hash if row else None, password)
            if (
                row is not None
                and valid
                and row.status == "active"
                and row.organization_status == "active"
            ):
                matches.append(row)
        if not matches:
            wait = await self._lockout.record_failure(key)
            for row in rows:
                async with self._db.tenant(row.organization_id) as session:
                    await _record(session, row, "candidate.portal.login.failed", ip, user_agent)
                    if wait is not None:
                        await _record(session, row, "candidate.portal.locked", ip, user_agent)
            return LoginRefused(wait)
        await self._lockout.reset(key)
        chosen = await self._choose(matches)
        now = _now()
        async with self._db.tenant(chosen.organization_id) as session:
            token, csrf, created = await create_portal_session(
                session,
                organization_id=chosen.organization_id,
                account_id=chosen.account_id,
                ip=ip,
                user_agent=user_agent,
                settings=self._settings,
                now=now,
            )
            await _record(session, chosen, "candidate.portal.login.succeeded", ip, user_agent)
        context = PortalSession(
            created.id, chosen.account_id, chosen.organization_id, created.csrf_hash
        )
        return PortalLoginOk(token, csrf, context)

    async def _choose(self, matches: list[AccountRow]) -> AccountRow:
        """One person may be a candidate of several organisations: the one with the soonest
        interview still to take, else the newest account."""
        now = _now()
        best: tuple[datetime, AccountRow] | None = None
        for row in matches:
            async with self._db.tenant(row.organization_id) as session:
                account = await session.get_one(CandidateAccount, row.account_id)
                evaluation = await evaluate(session, account, now)
            if evaluation.eligible:
                soonest = evaluation.eligible[0][0].starts_at
                if best is None or soonest < best[0]:
                    best = (soonest, row)
        return best[1] if best is not None else matches[-1]

    async def logout(
        self, context: PortalSession, *, ip: str | None, user_agent: str | None
    ) -> None:
        async with self._db.tenant(context.organization_id) as session:
            await revoke_portal_sessions(
                session, account_id=context.account_id, now=_now(), only=context.session_id
            )
            await _record_account(
                session,
                context.organization_id,
                context.account_id,
                "candidate.portal.logout",
                ip,
                user_agent,
            )

    async def view(self, context: PortalSession) -> PortalView:
        async with self._db.tenant(context.organization_id) as session:
            account = await session.get_one(CandidateAccount, context.account_id)
            organization = await session.get_one(Organization, context.organization_id)
        return PortalView(
            account_id=account.id,
            name=account.name,
            email=account.email,
            locale=account.locale,
            organization_id=organization.id,
            organization_name=organization.name,
            support_email=organization.support_email or self._settings.support_email,
        )

    # Passwords

    async def set_password(
        self, token: str, new: str, *, ip: str | None, user_agent: str | None
    ) -> list[PasswordOutcome] | None:
        """The invitation's link: sets the first password, which activates the account."""
        return await self._from_link(token, "set_password", new, ip, user_agent)

    async def reset_password(
        self, token: str, new: str, *, ip: str | None, user_agent: str | None
    ) -> list[PasswordOutcome] | None:
        """A forgotten password's link: a new password, and every session and sign-in ends."""
        return await self._from_link(token, "reset_password", new, ip, user_agent)

    async def request_reset(self, email: str, *, ip: str | None, user_agent: str | None) -> None:
        """Emails each matching account a link: a reset when it's active, a fresh invitation
        link while it's still invited. Returns the same way when there is none."""
        for row in await find_accounts(self._db, email.strip()):
            if row.organization_status != "active" or row.status not in ("active", "invited"):
                continue
            async with self._db.tenant(row.organization_id) as session:
                account = await session.get_one(CandidateAccount, row.account_id)
                if account.status == "invited":
                    hours = self._settings.candidate_link_hours
                    link = await self._link(session, account, "set_password", hours * 60)
                    minutes = hours * 60
                    path = "/invitation/"
                else:
                    minutes = self._settings.reset_token_minutes
                    link = await self._link(session, account, "reset_password", minutes)
                    path = "/reset-password/"
                await queue_mail(
                    session,
                    organization_id=account.organization_id,
                    template="reset_password",
                    to=account.email,
                    locale=account.locale,
                    context={
                        "name": account.name,
                        "link": f"{self._portal()}{path}{link}",
                        "minutes": str(minutes),
                    },
                )
                await _record(session, row, "candidate.password.reset_requested", ip, user_agent)

    async def _from_link(
        self,
        token: str,
        purpose: CandidateTokenPurpose,
        new: str,
        ip: str | None,
        user_agent: str | None,
    ) -> list[PasswordOutcome] | None:
        now = _now()
        ref = await lookup_candidate_token(self._db, token, purpose, now=now)
        if ref is None:
            return ["invalid_token"]
        async with self._db.tenant(ref.organization_id) as session:
            account = await session.get_one(CandidateAccount, ref.account_id)
            organization = await session.get_one(Organization, ref.organization_id)
            email, name, organization_name = account.email, account.name, organization.name
            status = account.status
        if status == "disabled":
            return ["invalid_token"]
        problems = await self._policy.check(
            new, email=email, name=name, organization=organization_name
        )
        if problems:
            # The link stays usable: it is claimed only when the password is accepted.
            return list(problems)
        password_hash = await hash_password_in_thread(new)
        async with self._db.tenant(ref.organization_id) as session:
            if not await claim_candidate_token(session, ref, now=now):
                return ["invalid_token"]
            account = await session.get_one(CandidateAccount, ref.account_id)
            account.password_hash = password_hash
            account.password_changed_at = now
            # Only the address's owner could follow the link.
            if account.email_verified_at is None:
                account.email_verified_at = now
            action = "candidate.password.reset"
            if account.status == "invited":
                account.status = "active"
                action = "candidate.account.activated"
            await revoke_portal_sessions(session, account_id=account.id, now=now)
            await session.execute(
                update(CandidateRefreshToken)
                .where(
                    CandidateRefreshToken.account_id == account.id,
                    CandidateRefreshToken.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            await _record_account(
                session, account.organization_id, account.id, action, ip, user_agent
            )
        await self._lockout.reset(candidate_lockout_key(email))
        return None

    async def _link(
        self,
        session: AsyncSession,
        account: CandidateAccount,
        purpose: CandidateTokenPurpose,
        minutes: int,
    ) -> str:
        return await issue_candidate_token(
            session, account, purpose, ttl=timedelta(minutes=minutes), now=_now()
        )

    def _portal(self) -> str:
        return self._settings.candidate_origin.rstrip("/")


async def _record(
    session: AsyncSession, row: AccountRow, action: str, ip: str | None, user_agent: str | None
) -> None:
    await _record_account(session, row.organization_id, row.account_id, action, ip, user_agent)


async def _record_account(
    session: AsyncSession,
    organization_id: UUID,
    account_id: UUID,
    action: str,
    ip: str | None,
    user_agent: str | None,
) -> None:
    await _audit.append(
        session,
        organization_id,
        AuditEntry(
            action=action,
            resource_type="candidate_account",
            resource_id=str(account_id),
            actor_type="candidate",
            actor_id=str(account_id),
            ip=ip,
            user_agent=user_agent,
        ),
    )


__all__ = ["PortalAuthService", "PortalLoginOk", "PortalView"]
