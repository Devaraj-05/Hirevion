"""`/api/v1/organization`: the signed-in user's organisation profile (PRD §9)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Request

from hirevion_api.access.deps import own_tenant
from hirevion_api.access.schemas import (
    CandidateAccessSettings,
    OrganizationProfileResponse,
    OrganizationProfileUpdate,
    patched,
)
from hirevion_api.authz import Principal, requires
from hirevion_api.routing import api_router
from hirevion_core.access.organization import (
    ProfileChanges,
    candidate_access,
    get_profile,
    save_candidate_access,
    update_profile,
)

router = api_router(tags=["organization"])

ManagesOrganization = Annotated[Principal, requires("admin.organization.manage")]


@router.get("/organization")
async def get_organization(
    request: Request, principal: ManagesOrganization
) -> OrganizationProfileResponse:
    """The organisation's profile. The Platform organisation has none (403)."""
    async with own_tenant(request, principal) as session:
        organization = await get_profile(session, principal.actor(request))
        return OrganizationProfileResponse.model_validate(organization)


@router.patch("/organization")
async def update_organization(
    body: OrganizationProfileUpdate, request: Request, principal: ManagesOrganization
) -> OrganizationProfileResponse:
    """Changes the fields sent; `website: null` or `support_email: null` clears it."""
    async with own_tenant(request, principal) as session:
        organization = await update_profile(
            session, principal.actor(request), ProfileChanges(**patched(body))
        )
        return OrganizationProfileResponse.model_validate(organization)


@router.get("/organization/candidate-access")
async def get_candidate_access(
    request: Request, principal: ManagesOrganization
) -> CandidateAccessSettings:
    """How candidates sign in to the desktop app: whether a new device needs an emailed code."""
    async with own_tenant(request, principal) as session:
        return CandidateAccessSettings(**await candidate_access(session, principal.actor(request)))


@router.put("/organization/candidate-access")
async def update_candidate_access(
    body: CandidateAccessSettings, request: Request, principal: ManagesOrganization
) -> CandidateAccessSettings:
    async with own_tenant(request, principal) as session:
        saved = await save_candidate_access(session, principal.actor(request), body.model_dump())
        return CandidateAccessSettings(**saved)
