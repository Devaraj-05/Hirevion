"""System roles: created with each organisation, never edited (SP-02 spec, "Roles")."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.identity import PLATFORM_ORGANIZATION_ID
from hirevion_core.identity.permissions import ORGANIZATION_ROLES, SYSTEM_ROLE_NAMES
from hirevion_core.models import Role


async def ensure_system_roles(session: AsyncSession, organization_id: UUID) -> None:
    """Add whichever of the organisation's system roles are missing. The Platform organisation
    has only `super_admin`; every other organisation has the four organisation roles."""
    wanted = ("super_admin",) if organization_id == PLATFORM_ORGANIZATION_ID else ORGANIZATION_ROLES
    existing = set(
        (
            await session.scalars(
                select(Role.key).where(Role.organization_id == organization_id, Role.system)
            )
        ).all()
    )
    for key in wanted:
        if key not in existing:
            session.add(
                Role(
                    organization_id=organization_id,
                    key=key,
                    name=SYSTEM_ROLE_NAMES[key],
                    system=True,
                )
            )
    await session.flush()
