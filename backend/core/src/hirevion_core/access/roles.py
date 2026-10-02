"""Custom roles and the permission catalogue (PRD §9 "Roles, Permissions"; ADR-0014).

System roles are fixed: their permissions live in code, so a release can extend them. Custom
roles hold any permissions except the platform's, stored in `role_permissions`; a change reaches
their members on their next request. Nobody puts into a role, or edits a role holding, a
permission they don't hold themselves.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access import UNSET, Unset
from hirevion_core.access.actor import Actor
from hirevion_core.access.audit import record
from hirevion_core.access.errors import Conflict, Invalid, NotFound, Refused
from hirevion_core.identity.permissions import (
    ASSIGNABLE_PERMISSIONS,
    SYSTEM_ROLE_NAMES,
    permissions_for,
)
from hirevion_core.models import Role, RolePermission, UserRole

NAME_MAX = 60
DESCRIPTION_MAX = 500
_SYSTEM_ORDER = {key: index for index, key in enumerate(SYSTEM_ROLE_NAMES)}


@dataclass(frozen=True, slots=True)
class RoleSummary:
    role: Role
    permissions: list[str]
    """What the role grants, the baseline included, in catalogue order."""
    member_count: int


def catalogue() -> list[tuple[str, str]]:
    """Every permission a custom role may hold, with its area (the part before the first dot),
    in catalogue order."""
    return [(name, name.split(".", 1)[0]) for name in ASSIGNABLE_PERMISSIONS]


async def _summaries(session: AsyncSession, found: Sequence[Role]) -> list[RoleSummary]:
    ids = [role.id for role in found]
    stored: dict[UUID, list[str]] = {role_id: [] for role_id in ids}
    counts: dict[UUID, int] = dict.fromkeys(ids, 0)
    if ids:
        for role_id, permission in await session.execute(
            select(RolePermission.role_id, RolePermission.permission).where(
                RolePermission.role_id.in_(ids)
            )
        ):
            stored[role_id].append(permission)
        for role_id, count in await session.execute(
            select(UserRole.role_id, func.count(UserRole.user_id))
            .where(UserRole.role_id.in_(ids))
            .group_by(UserRole.role_id)
        ):
            counts[role_id] = count
    summaries = [
        RoleSummary(
            role,
            permissions_for([role.key]) if role.key else permissions_for([], stored[role.id]),
            counts[role.id],
        )
        for role in found
    ]
    return sorted(
        summaries,
        key=lambda s: (
            (0, _SYSTEM_ORDER.get(s.role.key, 99), "")
            if s.role.key
            else (1, 0, s.role.name.lower())
        ),
    )


async def list_roles(session: AsyncSession) -> list[RoleSummary]:
    """System roles first, in PRD §6 order, then custom roles by name."""
    return await _summaries(session, (await session.scalars(select(Role))).all())


async def get_role(session: AsyncSession, role_id: UUID) -> RoleSummary:
    role = await session.get(Role, role_id)
    if role is None:
        raise NotFound("role-not-found", "No such role")
    return (await _summaries(session, [role]))[0]


def _name(value: str) -> str:
    name = value.strip()
    if not name or len(name) > NAME_MAX:
        raise Invalid("invalid-name", f"Use 1 to {NAME_MAX} characters", field="name")
    return name


def _description(value: str | None) -> str | None:
    description = (value or "").strip() or None
    if description is not None and len(description) > DESCRIPTION_MAX:
        raise Invalid(
            "invalid-description",
            f"Use at most {DESCRIPTION_MAX} characters",
            field="description",
        )
    return description


def _permissions(actor: Actor, requested: Sequence[str]) -> list[str]:
    unknown = sorted(set(requested) - set(ASSIGNABLE_PERMISSIONS))
    if unknown:
        raise Invalid(
            "unknown-permission",
            "A custom role can't hold these permissions",
            field="permissions",
            detail=", ".join(unknown),
        )
    missing = sorted(set(requested) - actor.permissions)
    if missing:
        raise Refused(
            "escalation", "You can't grant permissions you don't hold", detail=", ".join(missing)
        )
    return [p for p in ASSIGNABLE_PERMISSIONS if p in set(requested)]


async def _save(session: AsyncSession, role: Role) -> None:
    try:
        async with session.begin_nested():
            session.add(role)
    except IntegrityError as error:
        if "uq_roles_organization_id_name" in str(error.orig):
            raise Conflict("name-taken", "That name is already in use", field="name") from error
        raise


async def _editable(session: AsyncSession, actor: Actor, role_id: UUID) -> RoleSummary:
    summary = await get_role(session, role_id)
    if summary.role.system:
        raise Conflict("role-system", "Built-in roles can't be changed")
    if set(summary.permissions) - actor.permissions:
        raise Refused("outranked", "You can't change a role that holds permissions you don't")
    return summary


async def create_role(
    session: AsyncSession,
    actor: Actor,
    *,
    name: str,
    description: str | None,
    permissions: Sequence[str],
) -> RoleSummary:
    granted = _permissions(actor, permissions)
    role = Role(
        organization_id=actor.organization_id,
        name=_name(name),
        description=_description(description),
        system=False,
    )
    await _save(session, role)
    session.add_all(
        RolePermission(organization_id=actor.organization_id, role_id=role.id, permission=p)
        for p in granted
    )
    await session.flush()
    await record(
        session,
        actor,
        "role.created",
        "role",
        role.id,
        details={"name": role.name, "permissions": granted},
    )
    return await get_role(session, role.id)


async def update_role(
    session: AsyncSession,
    actor: Actor,
    role_id: UUID,
    *,
    name: str | Unset = UNSET,
    description: str | Unset | None = UNSET,
    permissions: Sequence[str] | Unset = UNSET,
) -> RoleSummary:
    summary = await _editable(session, actor, role_id)
    role = summary.role
    changed: list[str] = []
    details: dict[str, object] = {}
    if not isinstance(name, Unset) and _name(name) != role.name:
        role.name = _name(name)
        changed.append("name")
    if not isinstance(description, Unset) and _description(description) != role.description:
        role.description = _description(description)
        changed.append("description")
    if changed:
        await _save(session, role)
    if not isinstance(permissions, Unset):
        wanted = set(_permissions(actor, permissions))
        current = set(
            (
                await session.scalars(
                    select(RolePermission.permission).where(RolePermission.role_id == role.id)
                )
            ).all()
        )
        if wanted != current:
            await session.execute(
                delete(RolePermission).where(
                    RolePermission.role_id == role.id,
                    RolePermission.permission.in_(current - wanted),
                )
            )
            session.add_all(
                RolePermission(organization_id=role.organization_id, role_id=role.id, permission=p)
                for p in wanted - current
            )
            await session.flush()
            changed.append("permissions")
            details = {"added": sorted(wanted - current), "removed": sorted(current - wanted)}
    if changed:
        await record(
            session,
            actor,
            "role.updated",
            "role",
            role.id,
            details={"fields": changed, **details},
        )
    return await get_role(session, role.id)


async def delete_role(session: AsyncSession, actor: Actor, role_id: UUID) -> None:
    summary = await _editable(session, actor, role_id)
    if summary.member_count:
        people = "person has" if summary.member_count == 1 else "people have"
        raise Conflict(
            "role-in-use",
            "Remove this role from everyone who has it first",
            detail=f"{summary.member_count} {people} this role.",
        )
    name = summary.role.name
    await session.delete(summary.role)
    await session.flush()
    await record(session, actor, "role.deleted", "role", role_id, details={"name": name})
