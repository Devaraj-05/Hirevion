"""Single-use emailed tokens: set a first password, reset one, or verify a new email.

A token is found without a tenant (`auth_token`), then claimed inside the tenant transaction
that acts on it, so a failed action leaves the token usable and two concurrent uses can't both
succeed. Only the token's SHA-256 is stored.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.db.session import Database
from hirevion_core.identity.sessions import hash_token, new_token
from hirevion_core.models import AuthToken

TokenPurpose = Literal["set_password", "reset_password", "verify_email"]


@dataclass(frozen=True, slots=True)
class TokenRef:
    token_id: UUID
    organization_id: UUID
    user_id: UUID
    new_email: str | None


async def issue_token(
    session: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    purpose: TokenPurpose,
    ttl: timedelta,
    now: datetime,
    new_email: str | None = None,
) -> str:
    token = new_token()
    session.add(
        AuthToken(
            organization_id=organization_id,
            user_id=user_id,
            purpose=purpose,
            token_hash=hash_token(token),
            new_email=new_email,
            created_at=now,
            expires_at=now + ttl,
        )
    )
    await session.flush()
    return token


async def lookup_token(
    db: Database, token: str, purpose: TokenPurpose, *, now: datetime
) -> TokenRef | None:
    """The unused, unexpired token for `purpose`, or None."""
    async with db.unscoped() as session:
        row = (
            await session.execute(
                text("SELECT * FROM auth_token(:hash, :purpose)"),
                {"hash": hash_token(token), "purpose": purpose},
            )
        ).first()
    if row is None or row.used_at is not None or row.expires_at <= now:
        return None
    return TokenRef(row.token_id, row.organization_id, row.user_id, row.new_email)


async def claim_token(session: AsyncSession, ref: TokenRef, *, now: datetime) -> AuthToken | None:
    """Marks the token used in the caller's tenant transaction; None if it was already used."""
    result = await session.execute(
        update(AuthToken)
        .where(AuthToken.id == ref.token_id, AuthToken.used_at.is_(None))
        .values(used_at=now)
        .returning(AuthToken)
    )
    return result.scalar_one_or_none()
