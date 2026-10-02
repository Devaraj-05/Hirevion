"""`/api/v1/platform/organizations`: the super admins' organisations (PRD §6 "Super Admin").

Every change needs a recent password and is recorded in both the organisation's audit chain and
the platform's, in one transaction that starts (and ends) in the Platform organisation.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_api.access.deps import idempotency_scope
from hirevion_api.access.schemas import (
    OrganizationAdminInvite,
    OrganizationCreate,
    OrganizationListingResponse,
    OrganizationSuspend,
)
from hirevion_api.authz import Principal, requires
from hirevion_api.deps import get_db
from hirevion_api.idempotency import Idempotency, idempotency
from hirevion_api.pagination import Page, PageParams, decode_cursor, encode_cursor, page_params
from hirevion_api.problems import ProblemError
from hirevion_api.routing import api_router
from hirevion_core.access import platform
from hirevion_core.access.platform import OrganizationListing
from hirevion_core.identity import PLATFORM_ORGANIZATION_ID
from hirevion_core.identity.settings import IdentitySettings

router = api_router(tags=["platform"])

ReadsOrganizations = Annotated[Principal, requires("platform.organizations.manage")]
ChangesOrganizations = Annotated[Principal, requires("platform.organizations.manage", step_up=True)]
_ORDER = "platform-organizations:name,id"


def listing_response(listing: OrganizationListing) -> OrganizationListingResponse:
    return OrganizationListingResponse(
        id=listing.id,
        name=listing.name,
        slug=listing.slug,
        status=listing.status,  # type: ignore[arg-type]
        created_at=listing.created_at,
        user_count=listing.user_count,
    )


def _settings(request: Request) -> IdentitySettings:
    settings: IdentitySettings = request.app.state.identity
    return settings


def _platform_tenant(request: Request) -> AbstractAsyncContextManager[AsyncSession]:
    return get_db(request).tenant(PLATFORM_ORGANIZATION_ID)


def _after(cursor: str | None) -> tuple[str, UUID] | None:
    if cursor is None:
        return None
    name, organization_id = decode_cursor(_ORDER, cursor)
    if not isinstance(name, str) or not isinstance(organization_id, UUID):
        raise ProblemError(400, "invalid-cursor", "Invalid cursor")
    return name, organization_id


@router.get("/platform/organizations")
async def list_organizations(
    request: Request,
    principal: ReadsOrganizations,
    page: Annotated[PageParams, Depends(page_params)],
    status: Literal["active", "suspended"] | None = None,
    q: Annotated[str | None, Query(max_length=200, description="Part of a name or slug.")] = None,
) -> Page[OrganizationListingResponse]:
    """Every organisation, the Platform one included, by name, with its user count."""
    async with _platform_tenant(request) as session:
        rows = await platform.list_organizations(
            session, query=q, status=status, after=_after(page.cursor), limit=page.limit + 1
        )
    next_cursor = None
    if len(rows) > page.limit:
        rows = rows[: page.limit]
        next_cursor = encode_cursor(_ORDER, [rows[-1].name, rows[-1].id])
    return Page(items=[listing_response(row) for row in rows], next_cursor=next_cursor)


@router.post("/platform/organizations", status_code=201)
async def create_organization(
    body: OrganizationCreate,
    request: Request,
    principal: ChangesOrganizations,
    idem: Annotated[Idempotency, Depends(idempotency)],
) -> OrganizationListingResponse:
    """A new organisation with its built-in roles and an invited first admin, who is emailed a
    link to set their password."""
    async with _platform_tenant(request) as session:

        async def create() -> OrganizationListingResponse:
            listing = await platform.create_organization(
                session,
                principal.actor(request),
                name=body.name,
                slug=body.slug,
                admin_name=body.admin_name,
                admin_email=body.admin_email,
                settings=_settings(request),
            )
            return listing_response(listing)

        return await idem.run(
            session, PLATFORM_ORGANIZATION_ID, idempotency_scope(principal), create
        )


@router.post("/platform/organizations/{organization_id}/suspend")
async def suspend_organization(
    organization_id: UUID,
    body: OrganizationSuspend,
    request: Request,
    principal: ChangesOrganizations,
) -> OrganizationListingResponse:
    """Suspends an organisation: its users' sessions end and nobody there can sign in."""
    async with _platform_tenant(request) as session:
        listing = await platform.set_organization_status(
            session, principal.actor(request), organization_id, suspended=True, reason=body.reason
        )
    return listing_response(listing)


@router.post("/platform/organizations/{organization_id}/reactivate")
async def reactivate_organization(
    organization_id: UUID, request: Request, principal: ChangesOrganizations
) -> OrganizationListingResponse:
    async with _platform_tenant(request) as session:
        listing = await platform.set_organization_status(
            session, principal.actor(request), organization_id, suspended=False, reason=None
        )
    return listing_response(listing)


@router.post("/platform/organizations/{organization_id}/admins", status_code=204)
async def invite_organization_admin(
    organization_id: UUID,
    body: OrganizationAdminInvite,
    request: Request,
    principal: ChangesOrganizations,
) -> Response:
    """Invites another organisation admin, for when the first invitation lapsed."""
    async with _platform_tenant(request) as session:
        await platform.invite_organization_admin(
            session,
            principal.actor(request),
            organization_id,
            name=body.name,
            email=body.email,
            settings=_settings(request),
        )
    return Response(status_code=204)
