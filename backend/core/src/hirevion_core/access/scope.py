"""The resource scope (ADR-0014): which of an organisation's work a user reaches.

A user is either organisation-wide (the default), or limited to work owned by one of their teams
or by themselves (`users.access_scope = 'teams'`). Archived teams don't count. Jobs and
candidates (SP-04) and interviews (SP-07) filter their queries with `scope_clause`; their own
assignment rules (a hiring manager's jobs, an interviewer's interviews) narrow it further.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.models import Team, TeamMember, User


@dataclass(frozen=True, slots=True)
class ResourceScope:
    user_id: UUID
    organization_wide: bool
    team_ids: frozenset[UUID]


async def resource_scope(session: AsyncSession, user_id: UUID) -> ResourceScope:
    access_scope = await session.scalar(select(User.access_scope).where(User.id == user_id))
    if access_scope != "teams":
        return ResourceScope(user_id, organization_wide=True, team_ids=frozenset())
    team_ids = await session.scalars(
        select(TeamMember.team_id)
        .join(Team, Team.id == TeamMember.team_id)
        .where(TeamMember.user_id == user_id, Team.archived_at.is_(None))
    )
    return ResourceScope(user_id, organization_wide=False, team_ids=frozenset(team_ids.all()))


def scope_clause(
    scope: ResourceScope, *, team_column: ColumnElement[Any], owner_column: ColumnElement[Any]
) -> ColumnElement[bool]:
    """A WHERE clause keeping only the rows `scope` reaches; `team_column` is the owning team
    and `owner_column` the owning user of each row."""
    if scope.organization_wide:
        return true()
    owned = owner_column == scope.user_id
    if not scope.team_ids:
        return owned
    return team_column.in_(scope.team_ids) | owned
