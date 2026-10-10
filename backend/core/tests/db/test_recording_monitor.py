"""Recording continuity (SP-12 Task 4): a track that stops arriving while the interview is in
progress raises `recording.gap` and `RECORDING_STATUS`, once, and closes when it resumes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.db.session import Database
from hirevion_core.interview_session import realtime
from hirevion_core.models import Interview, OutboxEvent, Recording
from hirevion_core.recordings.monitor import ContinuityMonitor
from hirevion_core.recordings.segments import SegmentDeclaration, request_upload

from .test_interviews_schema import insert_interview
from .test_recordings_schema import recording

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]
NOW = datetime.now(UTC).replace(microsecond=0)


class FakeSigner:
    def upload_url(self, organization_id: UUID, path: Any, expires: timedelta | None = None) -> str:
        return f"https://storage.test/{path}"


async def live_interview(
    admin_engine: AsyncEngine, org: UUID, make_hiring: Any, *, level: str = "standard"
) -> UUID:
    interview = await insert_interview(admin_engine, await make_hiring(org), status="in_progress")
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE interviews SET started_at = :at, "
                "policy = CAST(:policy AS jsonb) WHERE id = :id"
            ),
            {
                "at": NOW - timedelta(minutes=5),
                "policy": f'{{"proctoring_level": "{level}"}}',
                "id": interview,
            },
        )
    return interview


def steady(
    org: UUID, interview: UUID, *, silent: tuple[str, ...] = (), silent_for: int = 100
) -> list[Recording]:
    rows = []
    for track in ("screen-1", "camera", "mic"):
        ago = timedelta(seconds=silent_for if track in silent else 4)
        rows.append(
            recording(
                org,
                interview,
                track=track,
                first_seq=0,
                last_seq=9,
                last_segment_at=NOW - ago,
                last_ended_at=NOW - ago,
            )
        )
    return rows


async def gap_events(app_db: Database, org: UUID, interview: UUID) -> list[dict[str, Any]]:
    async with app_db.tenant(org) as session:
        events = (
            await session.scalars(
                select(OutboxEvent)
                .where(OutboxEvent.topic == "recording.gap")
                .order_by(OutboxEvent.created_at)
            )
        ).all()
    return [e.payload for e in events if e.payload["interview_id"] == str(interview)]


async def test_a_silent_track_raises_one_open_gap_and_a_status_event(
    app_db: Database,
    admin_engine: AsyncEngine,
    valkey: Redis,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    org = await make_organization("Acme")
    interview = await live_interview(admin_engine, org, make_hiring)
    async with app_db.tenant(org) as session:
        session.add_all(steady(org, interview, silent=("screen-1",)))
    monitor = ContinuityMonitor(app_db, valkey)
    await monitor.run_once(NOW)
    await monitor.run_once(NOW + timedelta(seconds=10))  # still silent: not reported again

    (gap,) = await gap_events(app_db, org, interview)
    assert (gap["track"], gap["kind"], gap["state"]) == ("screen-1", "stalled", "open")
    assert (gap["from_seq"], gap["to_seq"], gap["to_time"]) == (10, None, None)
    assert gap["from_time"] == (NOW - timedelta(seconds=100)).isoformat()
    assert gap["allowed_seconds"] == 30 and gap["silent_seconds"] >= 100
    async with app_db.tenant(org) as session:
        stalled = await session.scalar(
            select(Recording).where(
                Recording.interview_id == interview, Recording.track == "screen-1"
            )
        )
    assert stalled is not None and stalled.stalled_since is not None
    live = await realtime.read(valkey, interview)
    assert [(e.type, e.data["track"], e.data["status"]) for e in live] == [
        ("RECORDING_STATUS", "screen-1", "stalled")
    ]
    assert live[0].data["last_seq"] == 9


async def test_a_track_that_never_started_is_flagged_from_the_interview_start(
    app_db: Database,
    admin_engine: AsyncEngine,
    valkey: Redis,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    org = await make_organization("Acme")
    interview = await live_interview(admin_engine, org, make_hiring)
    async with app_db.tenant(org) as session:
        session.add_all([r for r in steady(org, interview) if r.track != "mic"])
    await ContinuityMonitor(app_db, valkey).run_once(NOW)
    (gap,) = await gap_events(app_db, org, interview)
    assert (gap["track"], gap["from_seq"]) == ("mic", 0)
    assert gap["from_time"] == (NOW - timedelta(minutes=5)).isoformat()


async def test_the_allowance_follows_the_proctoring_level_and_the_recording_policy(
    app_db: Database,
    admin_engine: AsyncEngine,
    valkey: Redis,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    org = await make_organization("Acme")
    relaxed = await live_interview(admin_engine, org, make_hiring, level="off")
    strict = await live_interview(admin_engine, org, make_hiring, level="strict")
    async with app_db.tenant(org) as session:
        # 50 s of silence: past `strict`'s 20 s, within `off`'s 120 s.
        for interview in (relaxed, strict):
            session.add_all(steady(org, interview, silent=("camera",), silent_for=50))
    await ContinuityMonitor(app_db, valkey).run_once(NOW)
    assert await gap_events(app_db, org, relaxed) == []
    (gap,) = await gap_events(app_db, org, strict)
    assert (gap["track"], gap["allowed_seconds"]) == ("camera", 20)


async def test_interviews_that_are_not_in_progress_are_not_watched(
    app_db: Database,
    admin_engine: AsyncEngine,
    valkey: Redis,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    org = await make_organization("Acme")
    interview = await live_interview(admin_engine, org, make_hiring)
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE interviews SET status = 'interrupted' WHERE id = :id"), {"id": interview}
        )
    await ContinuityMonitor(app_db, valkey).run_once(NOW)
    assert await gap_events(app_db, org, interview) == []


async def test_a_stall_closes_when_the_next_segment_arrives(
    app_db: Database,
    admin_engine: AsyncEngine,
    valkey: Redis,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    org = await make_organization("Acme")
    interview = await live_interview(admin_engine, org, make_hiring)
    async with app_db.tenant(org) as session:
        session.add_all(steady(org, interview, silent=("screen-1",)))
    await ContinuityMonitor(app_db, valkey).run_once(NOW)

    resumed_at = NOW + timedelta(seconds=40)
    async with app_db.tenant(org) as session:
        row = await session.get_one(Interview, interview)
        _, notices = await request_upload(
            session,
            FakeSigner(),
            row,
            SegmentDeclaration(
                interview_id=interview,
                track="screen-1",
                seq=13,
                started_at=resumed_at - timedelta(seconds=10),
                duration_ms=10_000,
                bytes=1000,
                sha256="ab" * 32,
                container="mp4",
                codec="h264",
            ),
            now=resumed_at,
        )
    assert [(n.data["track"], n.data["status"]) for n in notices] == [("screen-1", "recording")]

    opened, closed = await gap_events(app_db, org, interview)
    assert (opened["state"], closed["state"], closed["kind"]) == ("open", "closed", "stalled")
    assert (closed["from_seq"], closed["to_seq"]) == (10, 12)  # 10 to 12 never came
    assert closed["to_time"] == (resumed_at - timedelta(seconds=10)).isoformat()
    assert closed["resumed_at"] == resumed_at.isoformat()
    async with app_db.tenant(org) as session:
        again = await session.scalar(
            select(Recording).where(
                Recording.interview_id == interview, Recording.track == "screen-1"
            )
        )
    assert again is not None and again.stalled_since is None and again.last_seq == 13
