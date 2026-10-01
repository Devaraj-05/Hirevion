"""`/api/v1/departments` and `/api/v1/teams` (PRD §9). Lists accept a neighbouring page's
permission too: the team dialog picks a department, and the users page picks teams."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request, Response

from hirevion_api.access.deps import idempotency_scope, own_tenant
from hirevion_api.access.schemas import (
    DepartmentCreate,
    DepartmentResponse,
    DepartmentUpdate,
    MemberResponse,
    TeamCreate,
    TeamResponse,
    TeamUpdate,
    patched,
)
from hirevion_api.authz import Principal, requires
from hirevion_api.idempotency import Idempotency, idempotency
from hirevion_api.routing import api_router
from hirevion_core.access import structure
from hirevion_core.access.structure import TeamSummary

router = api_router(tags=["structure"])

ManagesDepartments = Annotated[Principal, requires("admin.departments.manage")]
ReadsDepartments = Annotated[Principal, requires("admin.departments.manage", "admin.teams.manage")]
ManagesTeams = Annotated[Principal, requires("admin.teams.manage")]
ReadsTeams = Annotated[Principal, requires("admin.teams.manage", "admin.users.manage")]
Idempotent = Annotated[Idempotency, Depends(idempotency)]


def team_response(summary: TeamSummary) -> TeamResponse:
    team = summary.team
    return TeamResponse(
        id=team.id,
        name=team.name,
        description=team.description,
        department_id=team.department_id,
        department_name=summary.department_name,
        member_count=summary.member_count,
        archived_at=team.archived_at,
        created_at=team.created_at,
    )


# Departments


@router.get("/departments")
async def list_departments(
    request: Request, principal: ReadsDepartments, include_archived: bool = False
) -> list[DepartmentResponse]:
    """The organisation's departments by name; archived ones only when asked for."""
    async with own_tenant(request, principal) as session:
        departments = await structure.list_departments(session, include_archived=include_archived)
        return [DepartmentResponse.model_validate(d) for d in departments]


@router.post("/departments", status_code=201)
async def create_department(
    body: DepartmentCreate, request: Request, principal: ManagesDepartments, idem: Idempotent
) -> DepartmentResponse:
    async with own_tenant(request, principal) as session:

        async def create() -> DepartmentResponse:
            department = await structure.create_department(
                session, principal.actor(request), body.name, body.description
            )
            await session.refresh(department)
            return DepartmentResponse.model_validate(department)

        return await idem.run(
            session, principal.organization_id, idempotency_scope(principal), create
        )


@router.patch("/departments/{department_id}")
async def update_department(
    department_id: UUID, body: DepartmentUpdate, request: Request, principal: ManagesDepartments
) -> DepartmentResponse:
    """Renames, describes, archives (`archived: true`) or restores a department."""
    async with own_tenant(request, principal) as session:
        department = await structure.update_department(
            session, principal.actor(request), department_id, **patched(body)
        )
        await session.refresh(department)
        return DepartmentResponse.model_validate(department)


# Teams


@router.get("/teams")
async def list_teams(
    request: Request, principal: ReadsTeams, include_archived: bool = False
) -> list[TeamResponse]:
    """The organisation's teams by name, with their department and member count."""
    async with own_tenant(request, principal) as session:
        teams = await structure.list_teams(session, include_archived=include_archived)
        return [team_response(t) for t in teams]


@router.post("/teams", status_code=201)
async def create_team(
    body: TeamCreate, request: Request, principal: ManagesTeams, idem: Idempotent
) -> TeamResponse:
    async with own_tenant(request, principal) as session:

        async def create() -> TeamResponse:
            team = await structure.create_team(
                session, principal.actor(request), body.name, body.description, body.department_id
            )
            return team_response(await structure.get_team(session, team.id))

        return await idem.run(
            session, principal.organization_id, idempotency_scope(principal), create
        )


@router.patch("/teams/{team_id}")
async def update_team(
    team_id: UUID, body: TeamUpdate, request: Request, principal: ManagesTeams
) -> TeamResponse:
    """Renames, describes, moves, archives (`archived: true`) or restores a team."""
    async with own_tenant(request, principal) as session:
        await structure.update_team(session, principal.actor(request), team_id, **patched(body))
        return team_response(await structure.get_team(session, team_id))


@router.get("/teams/{team_id}/members")
async def list_team_members(
    team_id: UUID, request: Request, principal: ManagesTeams
) -> list[MemberResponse]:
    async with own_tenant(request, principal) as session:
        members = await structure.list_members(session, team_id)
        return [MemberResponse.model_validate(m) for m in members]


@router.put("/teams/{team_id}/members/{user_id}", status_code=204)
async def add_team_member(
    team_id: UUID, user_id: UUID, request: Request, principal: ManagesTeams
) -> Response:
    """Adds a user to the team; adding a member again changes nothing."""
    async with own_tenant(request, principal) as session:
        await structure.add_member(session, principal.actor(request), team_id, user_id)
    return Response(status_code=204)


@router.delete("/teams/{team_id}/members/{user_id}", status_code=204)
async def remove_team_member(
    team_id: UUID, user_id: UUID, request: Request, principal: ManagesTeams
) -> Response:
    async with own_tenant(request, principal) as session:
        await structure.remove_member(session, principal.actor(request), team_id, user_id)
    return Response(status_code=204)
