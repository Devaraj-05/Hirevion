"""The candidates' tabs follow the hiring status (SP-17; PRD §7, §72): a final decision takes a
candidate from "completed" to "decision"."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text

from hirevion_core.access.actor import Actor
from hirevion_core.access.scope import ResourceScope
from hirevion_core.candidates.candidates import CandidateFilters, candidates_statement
from hirevion_core.db.session import Database
from hirevion_core.hiring import workflow
from hirevion_core.identity.permissions import permissions_for

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]


async def test_a_final_decision_moves_the_candidate_from_completed_to_decision(
    app_db: Database, make_organization: MakeOrganization, make_completed_interview: Any
) -> None:
    org = await make_organization("Acme")
    scene = await make_completed_interview(org)
    recruiter = scene.hiring.recruiter_id
    application = scene.hiring.application_id
    everything = ResourceScope(recruiter, organization_wide=True, team_ids=frozenset())
    async with app_db.tenant(org) as session:
        await session.execute(
            text(
                "UPDATE applications SET stage = 'interviewed', "
                "hiring_status = 'interview_completed' WHERE id = :id"
            ),
            {"id": application},
        )

    async def tabs() -> dict[str, int]:
        found: dict[str, int] = {}
        async with app_db.tenant(org) as session:
            for group in ("completed", "decision"):
                rows = await session.scalars(
                    candidates_statement(everything, CandidateFilters(stage_group=group))
                )
                found[group] = len(rows.all())
        return found

    assert await tabs() == {"completed": 1, "decision": 0}
    async with app_db.tenant(org) as session:
        await workflow.change_status(
            session,
            Actor(recruiter, org, frozenset(permissions_for(["recruiter"]))),
            application,
            "selected",
            reason="Strong across the board",
        )
    assert await tabs() == {"completed": 0, "decision": 1}
