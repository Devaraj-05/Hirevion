"""The proctoring tables (SP-14): tenant isolation, the platform catalogue's invariants, the
idempotency keys, insert-only reviews, and the watcher's view of sessions."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.db.session import Database
from hirevion_core.ids import uuid7
from hirevion_core.models import AppCategory, AppRule, ProctorEvent, ProctorSession

from .test_interviews_schema import insert_interview

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]
NOW = datetime.now(UTC)


async def session_row(
    engine: AsyncEngine,
    organization_id: UUID,
    interview_id: UUID,
    *,
    watch_at: datetime | None = None,
) -> UUID:
    session_id = uuid7()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO proctor_sessions (id, organization_id, interview_id, level, "
                "policy_version, watch_at) VALUES (:id, :org, :iv, 'standard', 1, :watch)"
            ),
            {"id": session_id, "org": organization_id, "iv": interview_id, "watch": watch_at},
        )
    return session_id


async def event_row(
    engine: AsyncEngine,
    organization_id: UUID,
    interview_id: UUID,
    session_id: UUID,
    *,
    seq: int | None = 1,
    event: str = "FACE_ABSENT",
    phase: str | None = None,
    at: datetime = NOW,
) -> UUID:
    event_id = uuid7()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO proctor_events (id, organization_id, proctor_session_id, "
                "interview_id, seq, event, source, started_at, severity, phase, policy_version) "
                "VALUES (:id, :org, :session, :iv, :seq, :event, 'camera', :at, 'WARNING', "
                ":phase, 1)"
            ),
            {
                "id": event_id,
                "org": organization_id,
                "session": session_id,
                "iv": interview_id,
                "seq": seq,
                "event": event,
                "phase": phase,
                "at": at,
            },
        )
    return event_id


async def test_sessions_and_events_are_tenant_scoped(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    acme, globex = await make_organization("Acme"), await make_organization("Globex")
    mine = await insert_interview(admin_engine, await make_hiring(acme), status="in_progress")
    theirs = await insert_interview(admin_engine, await make_hiring(globex), status="in_progress")
    for org, interview in ((acme, mine), (globex, theirs)):
        sid = await session_row(admin_engine, org, interview)
        await event_row(admin_engine, org, interview, sid)
    async with app_db.tenant(acme) as session:
        assert (await session.scalars(select(ProctorSession.interview_id))).all() == [mine]
        assert (await session.scalars(select(ProctorEvent.interview_id))).all() == [mine]


async def test_a_sequence_number_is_stored_once_per_session_and_an_episode_is_one_row(
    admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    org = await make_organization("Acme")
    interview = await insert_interview(admin_engine, await make_hiring(org), status="in_progress")
    sid = await session_row(admin_engine, org, interview)
    await event_row(admin_engine, org, interview, sid, seq=1)
    with pytest.raises(IntegrityError):
        await event_row(admin_engine, org, interview, sid, seq=1, event="WINDOW_MINIMIZED")
    # Server events have no sequence number, and may repeat.
    await event_row(admin_engine, org, interview, sid, seq=None, event="TELEMETRY_GAP")
    await event_row(admin_engine, org, interview, sid, seq=None, event="TELEMETRY_GAP")
    await event_row(admin_engine, org, interview, sid, seq=2, phase="started")
    with pytest.raises(IntegrityError):
        await event_row(admin_engine, org, interview, sid, seq=3, phase="ended")


async def test_one_proctor_session_per_interview(
    admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    org = await make_organization("Acme")
    interview = await insert_interview(admin_engine, await make_hiring(org), status="in_progress")
    await session_row(admin_engine, org, interview)
    with pytest.raises(IntegrityError):
        await session_row(admin_engine, org, interview)


async def test_reviews_are_insert_only_and_need_a_reason(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring,
    make_user,
) -> None:
    org = await make_organization("Acme")
    reviewer = await make_user(org, roles=["recruiter"])
    interview = await insert_interview(admin_engine, await make_hiring(org), status="in_progress")
    sid = await session_row(admin_engine, org, interview)
    event = await event_row(admin_engine, org, interview, sid)
    insert = text(
        "INSERT INTO proctor_event_reviews (id, organization_id, proctor_event_id, interview_id, "
        "reviewer_id, outcome, reason) VALUES (:id, :org, :event, :iv, :user, 'false_positive', "
        ":reason)"
    )
    params = {"org": org, "event": event, "iv": interview, "user": reviewer}
    async with app_db.tenant(org) as session:
        await session.execute(insert, {**params, "id": uuid7(), "reason": "Reading the question"})
    with pytest.raises(IntegrityError):
        async with app_db.tenant(org) as session:
            await session.execute(insert, {**params, "id": uuid7(), "reason": "   "})
    for statement in (
        "UPDATE proctor_event_reviews SET reason = 'changed'",
        "DELETE FROM proctor_event_reviews",
    ):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with app_db.tenant(org) as session:
                await session.execute(text(statement))


async def test_the_platform_catalogue_is_seeded_and_never_blocks_on_a_name_alone(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    acme, globex = await make_organization("Acme"), await make_organization("Globex")
    async with app_db.tenant(acme) as session:
        categories = {row.key: row for row in await session.scalars(select(AppCategory))}
        rules = (
            await session.scalars(select(AppRule).where(AppRule.organization_id.is_(None)))
        ).all()
    assert set(categories) >= {
        "remote_access",
        "screen_sharing",
        "ai_assistant",
        "messaging",
        "screen_recorder",
        "virtual_machine",
    }
    assert len(rules) >= 30 and {rule.category_key for rule in rules} == set(categories)
    for rule in rules:
        assert rule.action == "block"
        assert rule.match != "name" or rule.conditions, f"{rule.value} would block on a name alone"
    # An organisation's own rule is seen by it alone, next to the platform's.
    async with app_db.tenant(acme) as session:
        session.add(
            AppRule(
                organization_id=acme,
                category_key="messaging",
                match="window_title",
                value="Internal chat",
            )
        )
    async with app_db.tenant(acme) as session:
        own = (await session.scalars(select(AppRule).where(AppRule.organization_id == acme))).all()
        assert [rule.value for rule in own] == ["Internal chat"]
    async with app_db.tenant(globex) as session:
        values = {rule.value for rule in await session.scalars(select(AppRule))}
    assert "Internal chat" not in values and "TeamViewer Germany GmbH" in values


async def test_the_database_refuses_a_blocking_rule_on_a_name_alone_and_foreign_platform_edits(
    app_db: Database, make_organization: MakeOrganization
) -> None:
    org = await make_organization("Acme")
    with pytest.raises(IntegrityError):
        async with app_db.tenant(org) as session:
            session.add(AppRule(organization_id=org, match="name", value="chrome.exe"))
    async with app_db.tenant(org) as session:
        session.add(AppRule(organization_id=org, action="allow", match="name", value="nvda.exe"))
    # The app role can't write the platform's catalogue (a row with no organisation).
    with pytest.raises(DBAPIError):
        async with app_db.tenant(org) as session:
            session.add(AppRule(organization_id=None, match="publisher", value="X"))
    async with app_db.tenant(org) as session:
        result = await session.execute(
            text("UPDATE app_rules SET enabled = false WHERE organization_id IS NULL")
        )
        assert result.rowcount == 0  # type: ignore[attr-defined]


async def test_the_watcher_lists_open_sessions_that_are_due(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    org = await make_organization("Acme")
    due = await insert_interview(admin_engine, await make_hiring(org), status="in_progress")
    later = await insert_interview(admin_engine, await make_hiring(org), status="in_progress")
    idle = await insert_interview(admin_engine, await make_hiring(org), status="in_progress")
    due_id = await session_row(admin_engine, org, due, watch_at=NOW - timedelta(seconds=1))
    await session_row(admin_engine, org, later, watch_at=NOW + timedelta(minutes=5))
    await session_row(admin_engine, org, idle)
    async with app_db.unscoped() as session:
        rows = await session.execute(
            text("SELECT * FROM scheduler_proctor_sessions_due(:now, 100000)"), {"now": NOW}
        )
        # Other tests leave sessions behind; this organisation has exactly the one that is due.
        assert [r.proctor_session_id for r in rows if r.organization_id == org] == [due_id]
