"""`/api/v1/roles` and `/api/v1/permissions`: custom roles and the permission matrix (PRD §9).
Defining roles needs `admin.roles.manage` and a recent password; the users page reads the
list for its role picker with `admin.users.manage`."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request, Response

from hirevion_api.access.deps import idempotency_scope, own_tenant
from hirevion_api.access.schemas import (
    PermissionResponse,
    RoleCreate,
    RoleResponse,
    RoleUpdate,
    patched,
)
from hirevion_api.authz import Principal, requires
from hirevion_api.idempotency import Idempotency, idempotency
from hirevion_api.routing import api_router
from hirevion_core.access import roles
from hirevion_core.access.roles import RoleSummary

router = api_router(tags=["roles"])

ReadsRoles = Annotated[Principal, requires("admin.roles.manage", "admin.users.manage")]
ManagesRoles = Annotated[Principal, requires("admin.roles.manage")]
ChangesRoles = Annotated[Principal, requires("admin.roles.manage", step_up=True)]


def role_response(summary: RoleSummary) -> RoleResponse:
    role = summary.role
    return RoleResponse(
        id=role.id,
        key=role.key,
        name=role.name,
        description=role.description,
        system=role.system,
        permissions=summary.permissions,
        member_count=summary.member_count,
    )


@router.get("/roles")
async def list_roles(request: Request, principal: ReadsRoles) -> list[RoleResponse]:
    """Built-in roles first, then the organisation's own, with what each grants."""
    async with own_tenant(request, principal) as session:
        return [role_response(summary) for summary in await roles.list_roles(session)]


@router.post("/roles", status_code=201)
async def create_role(
    body: RoleCreate,
    request: Request,
    principal: ChangesRoles,
    idem: Annotated[Idempotency, Depends(idempotency)],
) -> RoleResponse:
    """A custom role. It may hold only permissions you hold, and none of the platform's."""
    async with own_tenant(request, principal) as session:

        async def create() -> RoleResponse:
            summary = await roles.create_role(
                session,
                principal.actor(request),
                name=body.name,
                description=body.description,
                permissions=body.permissions,
            )
            return role_response(summary)

        return await idem.run(
            session, principal.organization_id, idempotency_scope(principal), create
        )


@router.patch("/roles/{role_id}")
async def update_role(
    role_id: UUID, body: RoleUpdate, request: Request, principal: ChangesRoles
) -> RoleResponse:
    """Renames, describes or re-grants a custom role; its members feel it on their next
    request. Built-in roles can't be changed."""
    async with own_tenant(request, principal) as session:
        summary = await roles.update_role(
            session, principal.actor(request), role_id, **patched(body)
        )
        return role_response(summary)


@router.delete("/roles/{role_id}", status_code=204)
async def delete_role(role_id: UUID, request: Request, principal: ChangesRoles) -> Response:
    """Deletes a custom role nobody holds."""
    async with own_tenant(request, principal) as session:
        await roles.delete_role(session, principal.actor(request), role_id)
    return Response(status_code=204)


@router.get("/permissions")
async def list_permissions(principal: ManagesRoles) -> list[PermissionResponse]:
    """Every permission a custom role may hold, grouped by area."""
    return [PermissionResponse(name=name, area=area) for name, area in roles.catalogue()]
