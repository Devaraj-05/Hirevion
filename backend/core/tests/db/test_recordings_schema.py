"""The recording tables (SP-12 Task 1): tenant isolation, one segment per (interview, track, seq),
the contract's limits as constraints, no deletes, and the worker's cross-tenant listings."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.db.session import Database
from hirevion_core.ids import uuid7
from hirevion_core.models import Recording, RecordingSegment
from hirevion_core.recordings.segments import ENDED_STATUSES

from .test_interviews_schema import insert_interview

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]
NOW = datetime.now(UTC)
SHA = "ab" * 32


def segment(org: UUID, interview: UUID, **changes: Any) -> RecordingSegment:
    fields: dict[str, Any] = {
        "id": uuid7(),
        "organization_id": org,
        "interview_id": interview,
        "track": "screen-1",
        "seq": 0,
        "started_at": NOW,
        "duration_ms": 10_000,
        "bytes": 1_843_921,
        "sha256": SHA,
        "container": "mp4",
        "codec": "h264",
        "blob_path": f"{org}/interviews/{interview}/screen/screen-1-000000.mp4",
    }
    return RecordingSegment(**{**fields, **changes})


def recording(org: UUID, interview: UUID, **changes: Any) -> Recording:
    fields: dict[str, Any] = {
        "id": uuid7(),
        "organization_id": org,
        "interview_id": interview,
        "track": "screen-1",
    }
    return Recording(**{**fields, **changes})


async def test_both_tables_are_tenant_scoped(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    acme, globex = await make_organization("Acme"), await make_organization("Globex")
    mine = await insert_interview(admin_engine, await make_hiring(acme), status="in_progress")
    theirs = await insert_interview(admin_engine, await make_hiring(globex), status="in_progress")
    for org, interview in ((acme, mine), (globex, theirs)):
        async with app_db.tenant(org) as session:
            session.add_all([segment(org, interview), recording(org, interview)])
    async with app_db.tenant(acme) as session:
        assert (await session.scalars(select(RecordingSegment.interview_id))).all() == [mine]
        assert (await session.scalars(select(Recording.interview_id))).all() == [mine]


async def test_a_row_cannot_point_at_another_organisations_interview(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    acme, globex = await make_organization("Acme"), await make_organization("Globex")
    theirs = await insert_interview(admin_engine, await make_hiring(globex), status="in_progress")
    with pytest.raises(IntegrityError):
        async with app_db.tenant(acme) as session:
            session.add(segment(acme, theirs))
    with pytest.raises(IntegrityError):
        async with app_db.tenant(acme) as session:
            session.add(recording(acme, theirs))


async def test_one_segment_per_interview_track_and_seq_and_one_recording_per_track(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    org = await make_organization("Acme")
    interview = await insert_interview(admin_engine, await make_hiring(org), status="in_progress")
    async with app_db.tenant(org) as session:
        session.add_all(
            [
                segment(org, interview, seq=0),
                segment(org, interview, seq=1),
                segment(org, interview, track="camera", seq=0, container="webm", codec="vp8"),
                recording(org, interview),
            ]
        )
    with pytest.raises(IntegrityError, match="uq_recording_segments_interview_id_track_seq"):
        async with app_db.tenant(org) as session:
            session.add(segment(org, interview, seq=1))
    with pytest.raises(IntegrityError, match="uq_recordings_interview_id_track"):
        async with app_db.tenant(org) as session:
            session.add(recording(org, interview))


@pytest.mark.parametrize(
    ("changes", "constraint"),
    [
        ({"track": "webcam"}, "track"),
        ({"track": "screen-9"}, "track"),
        ({"seq": -1}, "seq"),
        ({"duration_ms": 60_001}, "duration"),
        ({"duration_ms": 0}, "duration"),
        ({"bytes": 50_000_001}, "bytes"),
        ({"bytes": 0}, "bytes"),
        ({"sha256": "XYZ"}, "sha256"),
        ({"container": "avi"}, "container"),
        ({"codec": "h265"}, "codec"),
        ({"state": "done"}, "state"),
    ],
)
async def test_the_contracts_limits_are_constraints(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring,
    changes: dict[str, Any],
    constraint: str,
) -> None:
    org = await make_organization("Acme")
    interview = await insert_interview(admin_engine, await make_hiring(org), status="in_progress")
    with pytest.raises(IntegrityError, match=f"ck_recording_segments_{constraint}"):
        async with app_db.tenant(org) as session:
            session.add(segment(org, interview, **changes))


async def test_a_segment_moves_requested_to_uploaded_to_acknowledged(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    org = await make_organization("Acme")
    interview = await insert_interview(admin_engine, await make_hiring(org), status="in_progress")
    async with app_db.tenant(org) as session:
        row = segment(org, interview)
        session.add(row)
    assert (row.state, row.attempts) == ("requested", 0)
    for state in ("uploaded", "acknowledged"):
        async with app_db.tenant(org) as session:
            stored = await session.get_one(RecordingSegment, row.id)
            stored.state = state
    async with app_db.tenant(org) as session:
        assert (await session.get_one(RecordingSegment, row.id)).state == "acknowledged"


@pytest.mark.parametrize("statement", ["DELETE FROM recording_segments", "DELETE FROM recordings"])
async def test_the_app_cannot_delete_recordings(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring,
    statement: str,
) -> None:
    org = await make_organization("Acme")
    interview = await insert_interview(admin_engine, await make_hiring(org), status="in_progress")
    async with app_db.tenant(org) as session:
        session.add_all([segment(org, interview), recording(org, interview)])
    with pytest.raises(DBAPIError, match="permission denied"):
        async with app_db.tenant(org) as session:
            await session.execute(text(statement))


async def test_deleting_the_interview_takes_its_recordings_with_it(
    admin_engine: AsyncEngine, app_db: Database, make_organization: MakeOrganization, make_hiring
) -> None:
    org = await make_organization("Acme")
    interview = await insert_interview(admin_engine, await make_hiring(org), status="in_progress")
    async with app_db.tenant(org) as session:
        session.add_all([segment(org, interview), recording(org, interview)])
    async with admin_engine.begin() as conn:
        await conn.execute(text("DELETE FROM interviews WHERE id = :id"), {"id": interview})
        count = await conn.scalar(
            text(
                "SELECT (SELECT count(*) FROM recording_segments WHERE interview_id = :id) "
                "+ (SELECT count(*) FROM recordings WHERE interview_id = :id)"
            ),
            {"id": interview},
        )
    assert count == 0


async def test_the_worker_lists_recordings_due_for_assembly_across_organisations(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    acme, globex = await make_organization("Acme"), await make_organization("Globex")
    waiting = await insert_interview(admin_engine, await make_hiring(acme), status="completed")
    other = await insert_interview(admin_engine, await make_hiring(globex), status="completed")
    recording_ = await insert_interview(admin_engine, await make_hiring(acme), status="in_progress")
    backing_off = await insert_interview(admin_engine, await make_hiring(acme), status="completed")
    over = await insert_interview(admin_engine, await make_hiring(acme), status="completed")
    async with app_db.tenant(acme) as session:
        session.add_all(
            [
                recording(acme, waiting, status="assembly-pending"),
                recording(acme, waiting, track="mic", status="assembly-pending"),
                recording(acme, recording_),
                recording(acme, over),  # still `recording`, but the interview is over
                recording(
                    acme,
                    backing_off,
                    status="assembly-pending",
                    next_attempt_at=NOW + timedelta(minutes=5),
                ),
            ]
        )
    async with app_db.tenant(globex) as session:
        session.add(recording(globex, other, status="assembly-pending"))
    async with app_db.unscoped() as session:
        rows = await session.execute(
            text("SELECT * FROM recording_due_assembly(:now, 10000, :ended)"),
            {"now": NOW, "ended": list(ENDED_STATUSES)},
        )
        due = {
            (row.organization_id, row.interview_id)
            for row in rows
            if row.organization_id in (acme, globex)
        }
    # Once per interview, however many tracks.
    assert due == {(acme, waiting), (acme, over), (globex, other)}


async def test_the_worker_lists_the_tracks_of_interviews_in_progress(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization, make_hiring
) -> None:
    org = await make_organization("Acme")
    live = await insert_interview(admin_engine, await make_hiring(org), status="in_progress")
    silent = await insert_interview(admin_engine, await make_hiring(org), status="in_progress")
    done = await insert_interview(admin_engine, await make_hiring(org), status="completed")
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE interviews SET started_at = :at, policy = CAST(:policy AS jsonb) "
                "WHERE id IN (:live, :silent, :done)"
            ),
            {
                "at": NOW - timedelta(minutes=5),
                "policy": '{"proctoring_level": "strict"}',
                "live": live,
                "silent": silent,
                "done": done,
            },
        )
    async with app_db.tenant(org) as session:
        session.add_all(
            [
                recording(org, live, last_seq=4, last_segment_at=NOW, last_ended_at=NOW),
                recording(org, live, track="mic", last_seq=2, stalled_since=NOW),
                recording(org, done),
            ]
        )
    async with app_db.unscoped() as session:
        rows = (
            await session.execute(
                text("SELECT * FROM recording_live_tracks(:now, 10000)"), {"now": NOW}
            )
        ).all()
    by_interview: dict[UUID, list[Any]] = {}
    for row in rows:
        if row.organization_id == org:
            by_interview.setdefault(row.interview_id, []).append(row)
    assert set(by_interview) == {live, silent}  # a finished interview isn't watched
    assert {row.track for row in by_interview[live]} == {"screen-1", "mic"}
    assert [row.track for row in by_interview[silent]] == [None]  # nothing has arrived yet
    mic = next(row for row in by_interview[live] if row.track == "mic")
    assert mic.stalled is True and mic.last_seq == 2
    assert by_interview[live][0].policy == {"proctoring_level": "strict"}
    assert by_interview[live][0].started_at == NOW - timedelta(minutes=5)
