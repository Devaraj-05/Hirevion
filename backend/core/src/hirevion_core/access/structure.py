"""Departments and teams (PRD §9). Both are archived rather than deleted, so the work that will
point at them (jobs in SP-04) keeps its history; an archived team takes no new members and no
longer widens what its members see (`hirevion_core.access.scope`)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access import UNSET, Unset
from hirevion_core.access.actor import Actor
from hirevion_core.access.audit import record
from hirevion_core.access.errors import Conflict, Invalid, NotFound
from hirevion_core.models import Department, Team, TeamMember, User

NAME_MAX = 100
DESCRIPTION_MAX = 500


@dataclass(frozen=True, slots=True)
class TeamSummary:
    team: Team
    department_name: str | None
    member_count: int


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


async def _save(session: AsyncSession, row: Department | Team) -> None:
    """Writes `row` in a savepoint, so a duplicate name is a `name-taken` refusal even when
    another admin got there first."""
    try:
        async with session.begin_nested():
            session.add(row)
    except IntegrityError as error:
        if "_organization_id_name" in str(error.orig):
            raise Conflict("name-taken", "That name is already in use", field="name") from error
        raise


# Departments


async def list_departments(
    session: AsyncSession, *, include_archived: bool = False
) -> list[Department]:
    statement = select(Department).order_by(Department.name)
    if not include_archived:
        statement = statement.where(Department.archived_at.is_(None))
    return list((await session.scalars(statement)).all())


async def _department(session: AsyncSession, department_id: UUID) -> Department:
    department = await session.get(Department, department_id)
    if department is None:
        raise NotFound("department-not-found", "No such department")
    return department


async def create_department(
    session: AsyncSession, actor: Actor, name: str, description: str | None
) -> Department:
    department = Department(
        organization_id=actor.organization_id,
        name=_name(name),
        description=_description(description),
    )
    await _save(session, department)
    await record(
        session,
        actor,
        "department.created",
        "department",
        department.id,
        details={"name": department.name},
    )
    return department


async def update_department(
    session: AsyncSession,
    actor: Actor,
    department_id: UUID,
    *,
    name: str | Unset = UNSET,
    description: str | Unset | None = UNSET,
    archived: bool | None = None,
) -> Department:
    department = await _department(session, department_id)
    changed: list[str] = []
    if not isinstance(name, Unset) and _name(name) != department.name:
        department.name = _name(name)
        changed.append("name")
    if not isinstance(description, Unset) and _description(description) != department.description:
        department.description = _description(description)
        changed.append("description")
    if changed:
        await _save(session, department)
        await record(
            session,
            actor,
            "department.updated",
            "department",
            department.id,
            details={"fields": changed},
        )
    await _set_archived(session, actor, department, archived, "department")
    return department


# Teams


def _summaries() -> Select[Team, str, int]:
    # The department name is None for a team without one (outer join).
    return (
        select(Team, Department.name, func.count(TeamMember.user_id))
        .outerjoin(Department, Department.id == Team.department_id)
        .outerjoin(TeamMember, TeamMember.team_id == Team.id)
        .group_by(Team.id, Department.name)
        .order_by(Team.name)
    )


async def list_teams(session: AsyncSession, *, include_archived: bool = False) -> list[TeamSummary]:
    statement = _summaries()
    if not include_archived:
        statement = statement.where(Team.archived_at.is_(None))
    rows = (await session.execute(statement)).all()
    return [TeamSummary(team, department_name, count) for team, department_name, count in rows]


async def get_team(session: AsyncSession, team_id: UUID) -> TeamSummary:
    row = (await session.execute(_summaries().where(Team.id == team_id))).first()
    if row is None:
        raise NotFound("team-not-found", "No such team")
    team, department_name, count = row
    return TeamSummary(team, department_name, count)


async def _team(session: AsyncSession, team_id: UUID) -> Team:
    team = await session.get(Team, team_id)
    if team is None:
        raise NotFound("team-not-found", "No such team")
    return team


async def _live_department(session: AsyncSession, department_id: UUID | None) -> UUID | None:
    if department_id is None:
        return None
    department = await session.get(Department, department_id)
    if department is None or department.archived_at is not None:
        raise Invalid("invalid-department", "Choose a current department", field="department_id")
    return department.id


async def create_team(
    session: AsyncSession,
    actor: Actor,
    name: str,
    description: str | None,
    department_id: UUID | None,
) -> Team:
    team = Team(
        organization_id=actor.organization_id,
        name=_name(name),
        description=_description(description),
        department_id=await _live_department(session, department_id),
    )
    await _save(session, team)
    await record(
        session,
        actor,
        "team.created",
        "team",
        team.id,
        details={
            "name": team.name,
            "department_id": str(team.department_id) if team.department_id else None,
        },
    )
    return team


async def update_team(
    session: AsyncSession,
    actor: Actor,
    team_id: UUID,
    *,
    name: str | Unset = UNSET,
    description: str | Unset | None = UNSET,
    department_id: UUID | Unset | None = UNSET,
    archived: bool | None = None,
) -> Team:
    team = await _team(session, team_id)
    changed: list[str] = []
    if not isinstance(name, Unset) and _name(name) != team.name:
        team.name = _name(name)
        changed.append("name")
    if not isinstance(description, Unset) and _description(description) != team.description:
        team.description = _description(description)
        changed.append("description")
    if not isinstance(department_id, Unset) and department_id != team.department_id:
        team.department_id = await _live_department(session, department_id)
        changed.append("department_id")
    if changed:
        await _save(session, team)
        await record(session, actor, "team.updated", "team", team.id, details={"fields": changed})
    await _set_archived(session, actor, team, archived, "team")
    return team


async def list_members(session: AsyncSession, team_id: UUID) -> Sequence[User]:
    await _team(session, team_id)
    return (
        await session.scalars(
            select(User)
            .join(TeamMember, TeamMember.user_id == User.id)
            .where(TeamMember.team_id == team_id)
            .order_by(User.name, User.id)
        )
    ).all()


async def add_member(session: AsyncSession, actor: Actor, team_id: UUID, user_id: UUID) -> None:
    team = await _team(session, team_id)
    if team.archived_at is not None:
        raise Conflict("team-archived", "An archived team takes no new members")
    if await session.get(User, user_id) is None:
        raise NotFound("user-not-found", "No such user")
    if await session.get(TeamMember, (team_id, user_id)) is not None:
        return
    session.add(TeamMember(organization_id=actor.organization_id, team_id=team_id, user_id=user_id))
    await session.flush()
    await record(
        session, actor, "team.member.added", "team", team_id, details={"user_id": str(user_id)}
    )


async def remove_member(session: AsyncSession, actor: Actor, team_id: UUID, user_id: UUID) -> None:
    await _team(session, team_id)
    removed = await session.execute(
        delete(TeamMember)
        .where(TeamMember.team_id == team_id, TeamMember.user_id == user_id)
        .returning(TeamMember.user_id)
    )
    if removed.first() is not None:
        await record(
            session,
            actor,
            "team.member.removed",
            "team",
            team_id,
            details={"user_id": str(user_id)},
        )


async def _set_archived(
    session: AsyncSession,
    actor: Actor,
    row: Department | Team,
    archived: bool | None,
    kind: str,
) -> None:
    if archived is None or archived == (row.archived_at is not None):
        return
    row.archived_at = datetime.now(UTC) if archived else None
    await session.flush()
    action = f"{kind}.{'archived' if archived else 'restored'}"
    await record(session, actor, action, kind, row.id)
