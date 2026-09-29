"""The append-only, hash-chained audit log (master plan §7 and §9; PRD §97).

Each organisation has its own chain. Row `seq` stores
`hash = sha256(prev_hash || canonical_json(record))`, where `prev_hash` is the hash of row
`seq - 1` (32 zero bytes for the first row). Changing, removing or re-ordering a stored row
breaks every later link, and `verify_chain()` names the first broken `seq`.

Appends for one organisation queue on a transaction-scoped advisory lock, so `seq` has no gaps
or duplicates. Call `append()` inside `Database.tenant(organization_id)`; row-level security
rejects a row for any other organisation.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.ids import uuid7
from hirevion_core.models import AuditLog

GENESIS_HASH = bytes(32)


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """What happened: `action` (e.g. `"recording.viewed"`) on a resource, by an actor."""

    action: str
    resource_type: str
    resource_id: str | None = None
    actor_type: str = "system"
    actor_id: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChainCheck:
    ok: bool
    checked: int
    first_bad_seq: int | None


def canonical_json(record: Mapping[str, Any]) -> bytes:
    """Sorted keys, no whitespace, UTF-8; NaN and infinities are refused, as jsonb does."""
    return json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def chain_hash(prev: bytes, record: Mapping[str, Any]) -> bytes:
    return hashlib.sha256(prev + canonical_json(record)).digest()


def _normalise_ip(value: object) -> str | None:
    # PostgreSQL returns inet in its own spelling (lower-case, compressed IPv6); hash that one.
    return None if value is None else str(ipaddress.ip_interface(str(value)).ip)


def audit_record(
    row_id: UUID, organization_id: UUID, seq: int, occurred_at: datetime, entry: AuditEntry
) -> dict[str, Any]:
    """The hashed content of one row, in the form it reads back from the database."""
    if occurred_at.tzinfo is None:
        raise ValueError("audit times must carry a time zone")
    return {
        "id": str(row_id),
        "organization_id": str(organization_id),
        "seq": seq,
        "occurred_at": occurred_at.astimezone(UTC).isoformat(timespec="microseconds"),
        "actor_type": entry.actor_type,
        "actor_id": entry.actor_id,
        "action": entry.action,
        "resource_type": entry.resource_type,
        "resource_id": entry.resource_id,
        "ip": _normalise_ip(entry.ip),
        "user_agent": entry.user_agent,
        "details": dict(entry.details),
    }


def _entry_of(row: AuditLog) -> AuditEntry:
    return AuditEntry(
        action=row.action,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        actor_type=row.actor_type,
        actor_id=row.actor_id,
        ip=row.ip,
        user_agent=row.user_agent,
        details=row.details,
    )


class AuditService:
    async def append(
        self,
        session: AsyncSession,
        organization_id: UUID,
        entry: AuditEntry,
        now: datetime | None = None,
    ) -> AuditLog:
        """Append `entry` to the organisation's chain in the session's transaction."""
        occurred_at = datetime.now(UTC) if now is None else now
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"audit:{organization_id}"},
        )
        last = (
            await session.execute(
                select(AuditLog.seq, AuditLog.hash)
                .where(AuditLog.organization_id == organization_id)
                .order_by(AuditLog.seq.desc())
                .limit(1)
            )
        ).first()
        seq, prev = (1, GENESIS_HASH) if last is None else (last.seq + 1, last.hash)

        row_id = uuid7()
        record = audit_record(row_id, organization_id, seq, occurred_at, entry)
        row = AuditLog(
            id=row_id,
            organization_id=organization_id,
            seq=seq,
            occurred_at=occurred_at,
            actor_type=entry.actor_type,
            actor_id=entry.actor_id,
            action=entry.action,
            resource_type=entry.resource_type,
            resource_id=entry.resource_id,
            ip=record["ip"],
            user_agent=entry.user_agent,
            details=record["details"],
            prev_hash=prev,
            hash=chain_hash(prev, record),
        )
        session.add(row)
        await session.flush()
        return row

    async def verify_chain(self, session: AsyncSession, organization_id: UUID) -> ChainCheck:
        """Recompute the organisation's chain in `seq` order and stop at the first bad row."""
        rows = await session.stream_scalars(
            select(AuditLog)
            .where(AuditLog.organization_id == organization_id)
            .order_by(AuditLog.seq)
            .execution_options(yield_per=500)
        )
        prev, checked = GENESIS_HASH, 0
        try:
            async for row in rows:
                checked += 1
                record = audit_record(
                    row.id, row.organization_id, row.seq, row.occurred_at, _entry_of(row)
                )
                if (
                    row.seq != checked
                    or row.prev_hash != prev
                    or row.hash != chain_hash(prev, record)
                ):
                    return ChainCheck(ok=False, checked=checked, first_bad_seq=row.seq)
                prev = row.hash
        finally:
            await rows.close()
        return ChainCheck(ok=True, checked=checked, first_bad_seq=None)
