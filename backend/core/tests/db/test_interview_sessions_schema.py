"""The interview engine's tables (SP-09 Task 1): tenant isolation, insert-only records, the
partitioned transcript, and the scheduler's view of interruptions."""

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.db.session import Database
from hirevion_core.ids import uuid7
from hirevion_core.interviews.scheduler import due_interviews
from hirevion_core.models import InterviewSession, TranscriptSegment

from .test_interviews_schema import insert_interview

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]
NOW = datetime.now(UTC)


async def _session_row(engine: AsyncEngine, organization_id: UUID, interview_id: UUID) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO interview_sessions (interview_id, organization_id, room, started_at, "
                "deadline_at) VALUES (:id, :org, :room, :now, :deadline)"
            ),
            {
                "id": interview_id,
                "org": organization_id,
                "room": f"iv-{interview_id}",
                "now": NOW,
                "deadline": NOW + timedelta(minutes=45),
            },
        )


async def _segment(engine: AsyncEngine, organization_id: UUID, interview_id: UUID) -> UUID:
    segment_id = uuid7()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO transcript_segments (id, occurred_at, organization_id, interview_id, "
                "seq, speaker, text, start_ms, end_ms) VALUES (:id, :at, :org, :iv, 1, 'ai', "
                "'Hello', 0, 900)"
            ),
            {"id": segment_id, "at": NOW, "org": organization_id, "iv": interview_id},
        )
    return segment_id


async def test_sessions_and_segments_are_tenant_scoped(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    acme, globex = await make_organization("Acme"), await make_organization("Globex")
    mine = await insert_interview(admin_engine, await make_hiring(acme), status="in_progress")
    theirs = await insert_interview(admin_engine, await make_hiring(globex), status="in_progress")
    for org, interview in ((acme, mine), (globex, theirs)):
        await _session_row(admin_engine, org, interview)
        await _segment(admin_engine, org, interview)
    async with app_db.tenant(acme) as session:
        assert (await session.scalars(select(InterviewSession.interview_id))).all() == [mine]
        assert (await session.scalars(select(TranscriptSegment.interview_id))).all() == [mine]


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE transcript_segments SET text = 'changed'",
        "DELETE FROM transcript_segments",
        "UPDATE consents SET complete = true",
        "UPDATE system_check_results SET passed = true",
        "DELETE FROM interview_answers",
    ],
)
async def test_records_are_insert_only_for_the_app(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring,
    statement: str,
) -> None:
    org = await make_organization("Acme")
    interview = await insert_interview(admin_engine, await make_hiring(org), status="in_progress")
    await _segment(admin_engine, org, interview)
    with pytest.raises(DBAPIError, match="permission denied"):
        async with app_db.tenant(org) as session:
            await session.execute(text(statement))


async def test_segments_land_in_a_partition(
    admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    org = await make_organization("Acme")
    interview = await insert_interview(admin_engine, await make_hiring(org), status="in_progress")
    segment = await _segment(admin_engine, org, interview)
    async with admin_engine.connect() as conn:
        partition = await conn.scalar(
            text("SELECT tableoid::regclass::text FROM transcript_segments WHERE id = :id"),
            {"id": segment},
        )
    assert partition is not None and partition.startswith("transcript_segments_")


async def test_the_scheduler_sees_interruptions_past_their_grace(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    org = await make_organization("Acme")
    stale = await insert_interview(admin_engine, await make_hiring(org), status="interrupted")
    fresh = await insert_interview(admin_engine, await make_hiring(org), status="interrupted")
    policy = json.dumps({"resume": {"grace_seconds": 120}})
    async with admin_engine.begin() as conn:
        for interview, ago in ((stale, 300), (fresh, 30)):
            await conn.execute(
                text("UPDATE interviews SET interrupted_at = :at, policy = :policy WHERE id = :id"),
                {"at": NOW - timedelta(seconds=ago), "policy": policy, "id": interview},
            )
    due = {interview for _, interview in await due_interviews(app_db, NOW)}
    assert stale in due
    assert fresh not in due
