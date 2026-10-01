"""What a user's roles grant them (ADR-0014). Read on every request, so a change to a role or to
someone's roles applies at once, without signing in again."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.identity.permissions import permissions_for
from hirevion_core.models import Role, RolePermission, UserRole


@dataclass(frozen=True, slots=True)
class Grants:
    role_keys: list[str]
    """The user's system roles, by key."""
    custom_roles: list[str]
    """The user's custom roles, by name."""
    permissions: list[str]
    """Everything they may do, in catalogue order."""


async def load_grants(session: AsyncSession, user_id: UUID) -> Grants:
    """The user's roles and permissions, read in the caller's tenant transaction."""
    rows = (
        await session.execute(
            select(Role.key, Role.name, RolePermission.permission)
            .join(UserRole, UserRole.role_id == Role.id)
            .outerjoin(RolePermission, RolePermission.role_id == Role.id)
            .where(UserRole.user_id == user_id)
        )
    ).all()
    role_keys = sorted({key for key, _, _ in rows if key is not None})
    custom_roles = sorted({name for key, name, _ in rows if key is None})
    granted = [permission for key, _, permission in rows if key is None and permission]
    return Grants(role_keys, custom_roles, permissions_for(role_keys, granted))
