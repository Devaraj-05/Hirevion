"""`hv audit-tail` (SP-17): the newest entries of an organisation's audit log, for an operator and
for the end-to-end suite, which shows that a report was viewed, a recording played, a PDF
downloaded and a score changed. Read-only; the log is append-only and hash-chained."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from hirevion_core.db.session import create_database
from hirevion_core.identity.bootstrap import SEED_ORGANIZATION_SLUG
from hirevion_core.settings import load_core_settings

DEFAULT_LIMIT = 50
MAX_LIMIT = 500


@dataclass(frozen=True, slots=True)
class AuditRow:
    seq: int
    occurred_at: str
    action: str
    actor_type: str
    actor_id: str | None
    resource_type: str
    resource_id: str | None
    details: dict[str, Any]

    def as_json(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "occurred_at": self.occurred_at,
            "action": self.action,
            "actor_type": self.actor_type,
            "actor_id": self.actor_id,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "details": self.details,
        }


async def audit_tail(
    *,
    slug: str = SEED_ORGANIZATION_SLUG,
    action: str | None = None,
    resource: str | None = None,
    limit: int = DEFAULT_LIMIT,
    database: str | None = None,
) -> list[AuditRow]:
    """The organisation's newest entries, newest first, optionally of one action or about one
    resource."""
    db = create_database(load_core_settings(), "admin", database)
    try:
        async with db.unscoped() as session:
            rows = await session.execute(
                text(
                    "SELECT a.seq, a.occurred_at, a.action, a.actor_type, a.actor_id, "
                    "a.resource_type, a.resource_id, a.details FROM audit_logs a "
                    "JOIN organizations o ON o.id = a.organization_id WHERE o.slug = :slug "
                    "AND (CAST(:action AS text) IS NULL OR a.action = :action) "
                    "AND (CAST(:resource AS text) IS NULL OR a.resource_id = :resource) "
                    "ORDER BY a.seq DESC LIMIT :limit"
                ),
                {
                    "slug": slug,
                    "action": action,
                    "resource": resource,
                    "limit": max(1, min(limit, MAX_LIMIT)),
                },
            )
            return [
                AuditRow(
                    seq=row.seq,
                    occurred_at=row.occurred_at.isoformat(),
                    action=row.action,
                    actor_type=row.actor_type,
                    actor_id=row.actor_id,
                    resource_type=row.resource_type,
                    resource_id=row.resource_id,
                    details=dict(row.details),
                )
                for row in rows
            ]
    finally:
        await db.dispose()


def as_json(rows: list[AuditRow]) -> str:
    return json.dumps([row.as_json() for row in rows], indent=2, default=str)
