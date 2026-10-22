"""Idempotency keys: a create retried with the same key takes effect once (ADR-0010).

`claim()` inserts the key in the caller's transaction, before the create runs, and `remember()`
stores the response in the same transaction. So the key exists exactly when the create
committed:

- a retry after that commit replays the stored response;
- a retry while the first request is still running waits for it (up to the lock timeout);
- a create that failed or rolled back leaves no key, so a retry runs again.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from hirevion_core.models import IdempotencyKey

LOCK_NOT_AVAILABLE = "55P03"


@dataclass(frozen=True, slots=True)
class StoredResponse:
    status_code: int
    body: Any


class IdempotencyKeyReused(Exception):
    """The key was already used for a request with a different method, path or body."""


class IdempotencyInProgress(Exception):
    """Another request with this key is still running."""


def _where(organization_id: UUID, scope: str, key: str) -> tuple[Any, ...]:
    return (
        IdempotencyKey.organization_id == organization_id,
        IdempotencyKey.scope == scope,
        IdempotencyKey.key == key,
    )


async def claim(
    session: AsyncSession,
    organization_id: UUID,
    scope: str,
    key: str,
    fingerprint: bytes,
    *,
    lock_timeout_ms: int = 5000,
) -> StoredResponse | None:
    """`None`: go ahead, then `remember()` the response. Otherwise, the response to replay."""
    # SET can't take a bound parameter; the value is an int made here, never request text.
    # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
    await session.execute(text(f"SET LOCAL lock_timeout = {int(lock_timeout_ms)}"))
    try:
        inserted = await session.scalar(
            insert(IdempotencyKey)
            .values(organization_id=organization_id, scope=scope, key=key, fingerprint=fingerprint)
            .on_conflict_do_nothing(index_elements=["organization_id", "scope", "key"])
            .returning(IdempotencyKey.key)
        )
    except DBAPIError as error:
        if getattr(error.orig, "sqlstate", None) == LOCK_NOT_AVAILABLE:
            raise IdempotencyInProgress(key) from error
        raise
    await session.execute(text("SET LOCAL lock_timeout TO DEFAULT"))
    if inserted is not None:
        return None

    stored = (
        await session.execute(
            select(
                IdempotencyKey.fingerprint, IdempotencyKey.status_code, IdempotencyKey.response
            ).where(*_where(organization_id, scope, key))
        )
    ).one()
    if stored.fingerprint != fingerprint:
        raise IdempotencyKeyReused(key)
    if stored.status_code is None:  # only a committed claim is visible, and it has a response
        raise IdempotencyInProgress(key)
    return StoredResponse(stored.status_code, stored.response)


async def remember(
    session: AsyncSession,
    organization_id: UUID,
    scope: str,
    key: str,
    status_code: int,
    body: Any,
) -> None:
    await session.execute(
        update(IdempotencyKey)
        .where(*_where(organization_id, scope, key))
        .values(status_code=status_code, response=body)
    )


async def purge_idempotency_keys(conn: AsyncConnection, older_than: timedelta) -> int:
    """Delete keys older than `older_than` for every organisation (run as the admin role)."""
    result = await conn.execute(
        text("DELETE FROM idempotency_keys WHERE created_at < now() - make_interval(secs => :age)"),
        {"age": older_than.total_seconds()},
    )
    return result.rowcount
