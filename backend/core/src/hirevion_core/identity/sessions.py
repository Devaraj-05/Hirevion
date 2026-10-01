"""Server-side web sessions (SP-02 spec, "Sign-in, sessions and CSRF").

A session is an opaque 256-bit token in an HttpOnly cookie; the database keeps only its SHA-256
(and the SHA-256 of the session's CSRF token). A session ends after 30 idle minutes, after 12
hours whatever happens, when it is revoked, or when its user or organisation stops being active.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.db.session import Database
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.models import WebSession

# last_seen_at is written at most this often, so a busy session isn't a write per request.
LAST_SEEN_RESOLUTION = timedelta(seconds=60)


@dataclass(frozen=True, slots=True)
class SessionContext:
    session_id: UUID
    user_id: UUID
    organization_id: UUID
    csrf_hash: bytes
    # When the user last confirmed their password in this session (step-up).
    stepped_up_at: datetime | None = None


def is_stepped_up(context: SessionContext, settings: IdentitySettings, now: datetime) -> bool:
    """Whether the session confirmed its password recently enough for a sensitive change."""
    return (
        context.stepped_up_at is not None and now - context.stepped_up_at <= settings.step_up_window
    )


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


async def create_session(
    session: AsyncSession,
    *,
    user_id: UUID,
    organization_id: UUID,
    ip: str | None,
    user_agent: str | None,
    settings: IdentitySettings,
    now: datetime,
) -> tuple[str, str, WebSession]:
    """A new session in the caller's tenant transaction: (session token, CSRF token, row)."""
    token, csrf = new_token(), new_token()
    row = WebSession(
        organization_id=organization_id,
        user_id=user_id,
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


async def resolve_session(
    db: Database, token: str, *, settings: IdentitySettings, now: datetime
) -> SessionContext | None:
    """The live session for `token`, or None. Found without a tenant (`auth_session`)."""
    async with db.unscoped() as session:
        row = (
            await session.execute(
                text("SELECT * FROM auth_session(:hash)"), {"hash": hash_token(token)}
            )
        ).first()
    if (
        row is None
        or row.revoked_at is not None
        or now >= row.expires_at
        or now - row.last_seen_at > settings.session_idle
        or row.user_status != "active"
        or row.organization_status != "active"
    ):
        return None
    if now - row.last_seen_at >= LAST_SEEN_RESOLUTION:
        async with db.tenant(row.organization_id) as session:
            await session.execute(
                update(WebSession).where(WebSession.id == row.session_id).values(last_seen_at=now)
            )
    return SessionContext(
        row.session_id, row.user_id, row.organization_id, row.csrf_hash, row.stepped_up_at
    )


async def mark_stepped_up(session: AsyncSession, *, session_id: UUID, now: datetime) -> None:
    await session.execute(
        update(WebSession).where(WebSession.id == session_id).values(stepped_up_at=now)
    )


async def revoke_session(
    session: AsyncSession, *, user_id: UUID, session_id: UUID, now: datetime
) -> bool:
    """Ends one of the user's own sessions; False if it isn't theirs or has already ended."""
    result = await session.execute(
        update(WebSession)
        .where(
            WebSession.id == session_id,
            WebSession.user_id == user_id,
            WebSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
        .returning(WebSession.id)
    )
    return result.first() is not None


async def revoke_all_sessions(
    session: AsyncSession, *, user_id: UUID, except_session: UUID | None, now: datetime
) -> int:
    """Ends every session of the user's, except `except_session`; returns how many ended."""
    conditions = [WebSession.user_id == user_id, WebSession.revoked_at.is_(None)]
    if except_session is not None:
        conditions.append(WebSession.id != except_session)
    result = await session.execute(
        update(WebSession).where(*conditions).values(revoked_at=now).returning(WebSession.id)
    )
    return len(result.all())


async def list_sessions(
    session: AsyncSession, *, user_id: UUID, settings: IdentitySettings, now: datetime
) -> list[WebSession]:
    """The user's live sessions, most recently active first."""
    return list(
        (
            await session.scalars(
                select(WebSession)
                .where(
                    WebSession.user_id == user_id,
                    WebSession.revoked_at.is_(None),
                    WebSession.expires_at > now,
                    WebSession.last_seen_at > now - settings.session_idle,
                )
                .order_by(WebSession.last_seen_at.desc())
            )
        ).all()
    )
