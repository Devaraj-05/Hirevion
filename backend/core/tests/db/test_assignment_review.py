"""D1 code review (found while reviewing the screening actions): a candidate who was rejected is
not invited, or re-invited, to an interview that was made before the rejection."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.access.actor import Actor
from hirevion_core.access.errors import Conflict
from hirevion_core.access.scope import ResourceScope
from hirevion_core.db.session import Database
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.ids import uuid7
from hirevion_core.interviews import assignment
from hirevion_core.interviews.assignment import Assignment
from hirevion_core.models import Application, Interview, Invitation

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]
SETTINGS = IdentitySettings(hibp_enabled=False)
NOW = datetime.now(UTC).replace(microsecond=0)
WINDOW = (NOW + timedelta(days=2), NOW + timedelta(days=3))
EVERYWHERE = ResourceScope(uuid7(), organization_wide=True, team_ids=frozenset())


def recruiter_of(hiring: Any) -> Actor:
    return Actor(
        hiring.recruiter_id,
        hiring.organization_id,
        frozenset(permissions_for(["recruiter"])),
    )


async def made(app_db: Database, hiring: Any, *, invite: bool) -> UUID:
    async with app_db.tenant(hiring.organization_id) as session:
        result = await assignment.assign(
            session,
            recruiter_of(hiring),
            Assignment(
                application_ids=[hiring.application_id],
                template_id=hiring.template_id,
                starts_at=WINDOW[0],
                expires_at=WINDOW[1],
                invite=invite,
            ),
            EVERYWHERE,
            settings=SETTINGS,
        )
    return result.created[0].id


async def test_an_expired_interview_is_not_rescheduled_for_a_rejected_candidate(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    hiring = await make_hiring(await make_organization("Acme"))
    interview_id = await made(app_db, hiring, invite=False)
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE interviews SET status = 'expired' WHERE id = :id"), {"id": interview_id}
        )
        await conn.execute(
            text(
                "UPDATE applications SET stage = 'rejected', hiring_status = 'rejected' "
                "WHERE id = :id"
            ),
            {"id": hiring.application_id},
        )
    async with app_db.tenant(hiring.organization_id) as session:
        interview = await session.get_one(Interview, interview_id)
        with pytest.raises(Conflict) as refusal:
            await assignment.reschedule(
                session, recruiter_of(hiring), interview, *WINDOW, reason=None, settings=SETTINGS
            )
        assert refusal.value.code == "application-closed"
    async with app_db.tenant(hiring.organization_id) as session:
        application = await session.get_one(Application, hiring.application_id)
        assert (application.stage, application.hiring_status) == ("rejected", "rejected")
        assert (await session.scalars(select(Invitation.id))).all() == []  # no email went out


async def test_a_scheduled_interview_is_not_invited_once_its_candidate_was_rejected(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    hiring = await make_hiring(await make_organization("Acme"))
    interview_id = await made(app_db, hiring, invite=False)
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE applications SET stage = 'rejected' WHERE id = :id"),
            {"id": hiring.application_id},
        )
    async with app_db.tenant(hiring.organization_id) as session:
        interview = await session.get_one(Interview, interview_id)
        with pytest.raises(Conflict) as refusal:
            await assignment.invite(session, recruiter_of(hiring), interview, settings=SETTINGS)
        assert refusal.value.code == "application-closed"
