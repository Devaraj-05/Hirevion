"""Audit entries for access changes (PRD §97 "Permissions changed"), by the acting user."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.actor import Actor
from hirevion_core.audit import AuditEntry, AuditService

_audit = AuditService()


async def record(
    session: AsyncSession,
    actor: Actor,
    action: str,
    resource_type: str,
    resource_id: UUID | str | None,
    *,
    organization_id: UUID | None = None,
    details: Mapping[str, object] | None = None,
) -> None:
    """Appends to `organization_id`'s chain (the actor's own by default), which must be the
    session's current tenant. Platform actions name the organisation they changed and say so in
    the details (`{"via": "platform"}`)."""
    await _audit.append(
        session,
        organization_id or actor.organization_id,
        AuditEntry(
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else None,
            actor_type="user",
            actor_id=str(actor.user_id),
            ip=actor.ip,
            user_agent=actor.user_agent,
            details=dict(details or {}),
        ),
    )
