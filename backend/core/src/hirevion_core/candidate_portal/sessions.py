"""Candidates' web sessions on the portal (ADR-0022): ADR-0013's sessions for candidate accounts.

An opaque 256-bit token in its own `__Host-` cookie; the database keeps only its SHA-256 and the
SHA-256 of the session's CSRF token. A session ends after the recruiter's idle and absolute
limits, when it's revoked, or when its account or organisation stops being active.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.db.session import Database
from hirevion_core.identity.sessions import LAST_SEEN_RESOLUTION, hash_token, new_token
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.models import CandidateWebSession


@dataclass(frozen=True, slots=True)
class PortalSession:
    session_id: UUID
    account_id: UUID
    organization_id: UUID
    csrf_hash: bytes


async def create_portal_session(
    session: AsyncSession,
    *,
    organization_id: UUID,
    account_id: UUID,
    ip: str | None,
    user_agent: str | None,
    settings: IdentitySettings,
    now: datetime,
) -> tuple[str, str, CandidateWebSession]:
    """A new session in the caller's tenant transaction: (session token, CSRF token, row)."""
    token, csrf = new_token(), new_token()
    row = CandidateWebSession(
        organization_id=organization_id,
        account_id=account_id,
        token_hash=hash_token(token),
        csrf_hash=hash_token(csrf),
        created_at=now,
        last_seen_at=now,
        expires_at=now + settings.session_absolute,
        ip=ip,
        user_agent=user_agent[:512] if user_agent else None,
    )
    session.add(row)
    await session.flush()
    return token, csrf, row


async def resolve_portal_session(
    db: Database, token: str, *, settings: IdentitySettings, now: datetime
) -> PortalSession | None:
    """The live session for `token`, or None. Found without a tenant (`auth_candidate_session`)."""
    async with db.unscoped() as session:
        row = (
            await session.execute(
                text("SELECT * FROM auth_candidate_session(:hash)"), {"hash": hash_token(token)}
            )
        ).first()
    if (
        row is None
        or row.revoked_at is not None
        or now >= row.expires_at
        or now - row.last_seen_at > settings.session_idle
        or row.account_status != "active"
        or row.organization_status != "active"
    ):
        return None
    if now - row.last_seen_at >= LAST_SEEN_RESOLUTION:
        async with db.tenant(row.organization_id) as session:
            await session.execute(
                update(CandidateWebSession)
                .where(CandidateWebSession.id == row.session_id)
                .values(last_seen_at=now)
            )
    return PortalSession(row.session_id, row.account_id, row.organization_id, row.csrf_hash)


async def revoke_portal_sessions(
    session: AsyncSession,
    *,
    account_id: UUID,
    now: datetime,
    only: UUID | None = None,
) -> None:
    """Ends the account's sessions: every one, or just `only`."""
    conditions = [
        CandidateWebSession.account_id == account_id,
        CandidateWebSession.revoked_at.is_(None),
    ]
    if only is not None:
        conditions.append(CandidateWebSession.id == only)
    await session.execute(update(CandidateWebSession).where(*conditions).values(revoked_at=now))
