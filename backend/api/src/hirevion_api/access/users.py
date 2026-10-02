"""`/api/v1/users`: the organisation's users and invitations (PRD §6, §9). Changes to roles or
to whether someone can sign in need a recent password confirmation (step-up)."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, Query, Request, Response

from hirevion_api.access.deps import idempotency_scope, own_tenant
from hirevion_api.access.schemas import (
    RoleRef,
    TeamRef,
    UserInvite,
    UserResponse,
    UserRolesUpdate,
    UserUpdate,
    patched,
)
from hirevion_api.authz import Principal, requires
from hirevion_api.idempotency import Idempotency, idempotency
from hirevion_api.pagination import Page, PageParams, page_params, paginate
from hirevion_api.routing import api_router
from hirevion_core.access import users
from hirevion_core.access.users import Invitation, UserDetail, UserFilters
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.models import User

router = api_router(tags=["users"])

ManagesUsers = Annotated[Principal, requires("admin.users.manage")]
# The team page's member search reads the list too.
ReadsUsers = Annotated[Principal, requires("admin.users.manage", "admin.teams.manage")]
ChangesAccess = Annotated[Principal, requires("admin.users.manage", step_up=True)]


def user_response(detail: UserDetail) -> UserResponse:
    user = detail.user
    return UserResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        status=user.status,  # type: ignore[arg-type]
        access_scope=user.access_scope,  # type: ignore[arg-type]
        locale=user.locale,  # type: ignore[arg-type]
        roles=[RoleRef.model_validate(role) for role in detail.roles],
        teams=[TeamRef.model_validate(team) for team in detail.teams],
        created_at=user.created_at,
    )


def _settings(request: Request) -> IdentitySettings:
    settings: IdentitySettings = request.app.state.identity
    return settings


@router.get("/users")
async def list_users(
    request: Request,
    principal: ReadsUsers,
    page: Annotated[PageParams, Depends(page_params)],
    status: Literal["invited", "active", "disabled"] | None = None,
    role_id: UUID | None = None,
    team_id: UUID | None = None,
    q: Annotated[str | None, Query(max_length=200, description="Part of a name or email.")] = None,
) -> Page[UserResponse]:
    """The organisation's users by name, filtered by status, role, team or text."""
    filters = UserFilters(status=status, role_id=role_id, team_id=team_id, query=q)
    async with own_tenant(request, principal) as session:
        rows, next_cursor = await paginate(
            session, users.users_statement(filters), [User.name, User.id], page
        )
        details = await users.describe(session, rows)
        return Page(items=[user_response(d) for d in details], next_cursor=next_cursor)


@router.post("/users", status_code=201)
async def invite_user(
    body: UserInvite,
    request: Request,
    principal: ChangesAccess,
    idem: Annotated[Idempotency, Depends(idempotency)],
) -> UserResponse:
    """Invites someone: an `invited` user with the given roles and teams, emailed a link that
    sets their password (valid `HV_SET_PASSWORD_TOKEN_HOURS`)."""
    invitation = Invitation(
        email=body.email,
        name=body.name,
        role_ids=body.role_ids,
        team_ids=body.team_ids,
        access_scope=body.access_scope,
        locale=body.locale,
    )
    async with own_tenant(request, principal) as session:

        async def create() -> UserResponse:
            detail = await users.invite_user(
                session, principal.actor(request), invitation, settings=_settings(request)
            )
            await session.refresh(detail.user)
            return user_response(detail)

        return await idem.run(
            session, principal.organization_id, idempotency_scope(principal), create
        )


@router.get("/users/{user_id}")
async def get_user(user_id: UUID, request: Request, principal: ManagesUsers) -> UserResponse:
    async with own_tenant(request, principal) as session:
        return user_response(await users.get_user(session, user_id))


@router.patch("/users/{user_id}")
async def update_user(
    user_id: UUID, body: UserUpdate, request: Request, principal: ManagesUsers
) -> UserResponse:
    """Changes a user's name, access or teams (`team_ids` replaces them)."""
    async with own_tenant(request, principal) as session:
        detail = await users.update_user(
            session, principal.actor(request), user_id, **patched(body)
        )
        return user_response(detail)


@router.put("/users/{user_id}/roles")
async def set_user_roles(
    user_id: UUID, body: UserRolesUpdate, request: Request, principal: ChangesAccess
) -> UserResponse:
    """Replaces a user's roles. Nobody grants what they don't hold, and an organisation keeps
    one active admin."""
    async with own_tenant(request, principal) as session:
        return user_response(
            await users.set_roles(session, principal.actor(request), user_id, body.role_ids)
        )


@router.post("/users/{user_id}/disable")
async def disable_user(user_id: UUID, request: Request, principal: ChangesAccess) -> UserResponse:
    """Stops a user signing in; their sessions and emailed links end."""
    async with own_tenant(request, principal) as session:
        return user_response(await users.disable_user(session, principal.actor(request), user_id))


@router.post("/users/{user_id}/enable")
async def enable_user(user_id: UUID, request: Request, principal: ChangesAccess) -> UserResponse:
    async with own_tenant(request, principal) as session:
        return user_response(await users.enable_user(session, principal.actor(request), user_id))


@router.post("/users/{user_id}/invitation", status_code=204)
async def resend_invitation(user_id: UUID, request: Request, principal: ChangesAccess) -> Response:
    """Emails a new invitation link; the earlier ones stop working."""
    async with own_tenant(request, principal) as session:
        await users.resend_invitation(
            session, principal.actor(request), user_id, settings=_settings(request)
        )
    return Response(status_code=204)


@router.delete("/users/{user_id}", status_code=204)
async def cancel_invitation(user_id: UUID, request: Request, principal: ChangesAccess) -> Response:
    """Cancels an invitation. Users who signed in are disabled instead, never deleted."""
    async with own_tenant(request, principal) as session:
        await users.cancel_invitation(session, principal.actor(request), user_id)
    return Response(status_code=204)
