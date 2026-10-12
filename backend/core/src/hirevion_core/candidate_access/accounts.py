"""Candidate accounts and their single-use links (SP-07a; ADR-0020).

An account is created by a candidate's first invitation and stays `invited` until they set a
password from the emailed link. Accounts and links are found by email or token before the
tenant is known (`auth_candidate_by_email`, `auth_candidate_token`, ADR-0013's pattern), then
acted on inside the tenant's transaction, where a link is claimed so two uses can't both win.
Only SHA-256 hashes of links are stored.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.db.session import Database
from hirevion_core.identity.sessions import hash_token, new_token
from hirevion_core.models import Candidate, CandidateAccount, CandidateToken

CandidateTokenPurpose = Literal["set_password", "reset_password"]


@dataclass(frozen=True, slots=True)
class AccountRow:
    """An account found by email, before its tenant is known."""

    account_id: UUID
    organization_id: UUID
    status: str
    password_hash: str | None
    organization_status: str


@dataclass(frozen=True, slots=True)
class CandidateTokenRef:
    token_id: UUID
    organization_id: UUID
    account_id: UUID


def candidate_lockout_key(email: str) -> str:
    """The sign-in lockout's key for a candidate's email: one budget for the desktop app and
    the portal (ADR-0021, ADR-0022), kept apart from recruiters'."""
    return f"candidate:{email.strip()}"


async def ensure_account(
    session: AsyncSession, candidate: Candidate, *, locale: str
) -> CandidateAccount:
    """The candidate's account in their organisation, created `invited` if there is none. The
    candidate must have an email address."""
    if not candidate.email:
        raise ValueError("a candidate account needs an email address")
    account = await session.scalar(
        select(CandidateAccount).where(CandidateAccount.candidate_id == candidate.id)
    )
    if account is not None:
        if account.email.casefold() != candidate.email.casefold() and account.status == "invited":
            # Not yet used: follow the candidate's corrected address.
            account.email = candidate.email
        return account
    account = CandidateAccount(
        organization_id=candidate.organization_id,
        candidate_id=candidate.id,
        email=candidate.email,
        name=candidate.name,
        locale=locale,
        status="invited",
    )
    session.add(account)
    await session.flush()
    return account


async def issue_candidate_token(
    session: AsyncSession,
    account: CandidateAccount,
    purpose: CandidateTokenPurpose,
    *,
    ttl: timedelta,
    now: datetime,
) -> str:
    """A fresh link for `purpose`; earlier unused links for the same purpose stop working."""
    await revoke_candidate_tokens(session, account.id, now=now, purpose=purpose)
    token = new_token()
    session.add(
        CandidateToken(
            organization_id=account.organization_id,
            account_id=account.id,
            purpose=purpose,
            token_hash=hash_token(token),
            created_at=now,
            expires_at=now + ttl,
        )
    )
    await session.flush()
    return token


async def revoke_candidate_tokens(
    session: AsyncSession,
    account_id: UUID,
    *,
    now: datetime,
    purpose: CandidateTokenPurpose | None = None,
) -> None:
    conditions = [CandidateToken.account_id == account_id, CandidateToken.used_at.is_(None)]
    if purpose is not None:
        conditions.append(CandidateToken.purpose == purpose)
    await session.execute(update(CandidateToken).where(*conditions).values(used_at=now))


async def lookup_candidate_token(
    db: Database, token: str, purpose: CandidateTokenPurpose, *, now: datetime
) -> CandidateTokenRef | None:
    """The unused, unexpired link for `purpose`, found without a tenant; or None."""
    async with db.unscoped() as session:
        row = (
            await session.execute(
                text("SELECT * FROM auth_candidate_token(:hash, :purpose)"),
                {"hash": hash_token(token), "purpose": purpose},
            )
        ).first()
    if row is None or row.used_at is not None or row.expires_at <= now:
        return None
    return CandidateTokenRef(row.token_id, row.organization_id, row.account_id)


async def claim_candidate_token(
    session: AsyncSession, ref: CandidateTokenRef, *, now: datetime
) -> bool:
    """Marks the link used in the caller's tenant transaction; False if it already was."""
    result = await session.execute(
        update(CandidateToken)
        .where(CandidateToken.id == ref.token_id, CandidateToken.used_at.is_(None))
        .values(used_at=now)
        .returning(CandidateToken.id)
    )
    return result.scalar_one_or_none() is not None


async def find_accounts(db: Database, email: str) -> list[AccountRow]:
    """Every account with this email, in any organisation (at most ten), found without a
    tenant. One person may be a candidate of several organisations."""
    async with db.unscoped() as session:
        rows = (
            await session.execute(
                text("SELECT * FROM auth_candidate_by_email(:email)"), {"email": email.strip()}
            )
        ).all()
    return [
        AccountRow(
            row.account_id,
            row.organization_id,
            row.status,
            row.password_hash,
            row.organization_status,
        )
        for row in rows
    ]
