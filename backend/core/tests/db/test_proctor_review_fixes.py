# ruff: noqa: F811 (the fixtures are imported from test_proctor_engine)
"""Behaviour the C5 code review found missing (SP-14): gaps in the numbers that fill in, gaps in
recordings that overlap what the server saw or an excused interruption, naive timestamps,
evidence in a resent report, the server's clock on adopted rows, and the interview's summary
handed to the outbox."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select, text

from hirevion_core.db.session import Database
from hirevion_core.models import OutboxEvent, ProctorEvent, ProctorEvidence
from hirevion_core.proctoring.normaliser import Incoming
from hirevion_core.proctoring.watcher import handle_gap

from .test_proctor_engine import (  # noqa: F401  (fixtures)
    T0,
    World,
    clock,
    item,
    rows,
    set_interview,
    world,
)

pytestmark = pytest.mark.db


async def named(db: Database, w: World, name: str, **details: Any) -> list[ProctorEvent]:
    found = await rows(db, w, ProctorEvent.event == name)
    return [r for r in found if all(r.details.get(k) == v for k, v in details.items())]


# Finding 5: a gap in the numbers is reported only if it lasts.


async def test_a_sequence_gap_that_fills_in_raises_nothing(world: World, app_db: Database) -> None:
    await world.open()
    await world.send(item(1), item(3, at=1))
    assert await named(app_db, world, "TELEMETRY_GAP") == []
    world.clock.advance(5)
    await world.send(item(2, at=2))
    for _ in range(3):
        world.clock.advance(15)
        await world.beat()
        await world.tick()
    assert await named(app_db, world, "TELEMETRY_GAP") == []


async def test_a_sequence_gap_that_lasts_is_reported_once(world: World, app_db: Database) -> None:
    await world.open()
    await world.send(item(1), item(5, at=1))
    for _ in range(2):
        world.clock.advance(15)
        await world.beat()
        await world.tick()
    assert await named(app_db, world, "TELEMETRY_GAP") == []
    for _ in range(3):
        world.clock.advance(15)
        await world.beat()
        await world.tick()
    (gap,) = await named(app_db, world, "TELEMETRY_GAP", reason="sequence_gap")
    assert (gap.details["from_seq"], gap.details["to_seq"]) == (2, 4) and gap.severity == "WARNING"
    # Filling it later, in pieces, doesn't report it again or take it back.
    await world.send(item(3, at=2))
    world.clock.advance(15)
    await world.beat()
    await world.tick()
    assert len(await named(app_db, world, "TELEMETRY_GAP", reason="sequence_gap")) == 1


# Finding 2: one hole in a recording is one event.


def stall(w: World, track: str, state: str, **fields: Any) -> dict[str, Any]:
    return {
        "interview_id": str(w.interview),
        "track": track,
        "kind": "stalled",
        "state": state,
        "from_seq": 4,
        "to_seq": None,
        "from_time": T0.isoformat(),
        "to_time": None,
        **fields,
    }


async def test_a_hole_found_at_assembly_joins_the_stall_the_server_already_saw(
    world: World, app_db: Database
) -> None:
    await world.open()
    await world.beat()
    await handle_gap(world.engine, world.org, stall(world, "camera", "open"))
    world.clock.advance(20)
    await world.beat()
    await world.tick()
    end = world.clock.now
    await handle_gap(
        world.engine, world.org, stall(world, "camera", "closed", to_seq=6, to_time=end.isoformat())
    )
    world.clock.advance(1)
    await world.beat()
    await world.tick()
    assert len(await named(app_db, world, "TELEMETRY_GAP")) == 1
    missing = stall(world, "camera", "closed", kind="missing", to_seq=6, to_time=end.isoformat())
    await handle_gap(world.engine, world.org, missing)
    (gap,) = await named(app_db, world, "TELEMETRY_GAP")
    assert gap.details["recording_gap"]["kind"] == "missing"
    # Another track's hole in the same moments is another event.
    await handle_gap(world.engine, world.org, {**missing, "track": "mic"})
    assert len(await named(app_db, world, "TELEMETRY_GAP")) == 2


# Finding 3: an excused interruption isn't a gap in the recording.


async def interrupted_between(world: World, admin: Any, start: float, end: float) -> None:
    await world.beat()
    world.clock.advance(start)
    await set_interview(admin, world, status="interrupted")
    await world.tick()
    world.clock.advance(end - start)
    await set_interview(admin, world, status="in_progress")
    await world.tick()


async def test_a_hole_inside_an_interruption_is_not_a_violation(
    world: World, app_db: Database, admin_engine: Any
) -> None:
    await world.open()
    await interrupted_between(world, admin_engine, 10, 70)
    inside = T0 + timedelta(seconds=20)
    assert not await world.engine.record_gap(world.org, world.interview, "screen-1", inside, 30_000)
    assert await named(app_db, world, "SCREEN_CAPTURE_STOPPED") == []


async def test_only_the_part_of_a_hole_outside_an_interruption_counts(
    world: World, app_db: Database, admin_engine: Any
) -> None:
    await world.open()
    await interrupted_between(world, admin_engine, 10, 70)
    assert await world.engine.record_gap(world.org, world.interview, "screen-1", T0, 40_000)
    (gap,) = await named(app_db, world, "SCREEN_CAPTURE_STOPPED")
    assert gap.duration_ms == 10_000 and gap.severity == "WARNING"


# Finding 4: naive timestamps.


async def test_a_batch_may_mix_naive_and_aware_times(world: World, app_db: Database) -> None:
    await world.open()
    naive = Incoming(1, "PHONE_DETECTED", "camera", T0.replace(tzinfo=None))
    ack = await world.send(naive, item(2, "WINDOW_MINIMIZED", at=1, duration_ms=4000))
    assert ack.acked_through == 2
    first, second = await rows(app_db, world)
    assert first.started_at == T0 and second.started_at == T0 + timedelta(seconds=1)


# Finding 8: evidence in a resent report.


async def test_evidence_in_a_repeated_phase_is_still_attached(
    world: World, app_db: Database
) -> None:
    await world.open()
    from .test_proctor_engine import FakeUploads

    assert world.session_id is not None
    slot = await world.engine.evidence_upload(
        world.org,
        world.interview,
        world.session_id,
        FakeUploads(),
        kind="camera",
        seq=2,
        request_id=None,
        content_type="image/jpeg",
        size=900,
        sha256="a" * 64,
    )
    ended = {"phase": "ended"}
    await world.send(item(2, details=ended, duration_ms=40_000))
    # The same report again, from an earlier number that arrived late, now with its picture.
    await world.send(
        item(
            1,
            details=ended,
            duration_ms=40_000,
            evidence=[{"type": "snapshot", "blob_path": slot.blob_path}],
        )
    )
    async with app_db.tenant(world.org) as session:
        linked = (
            await session.scalars(
                select(ProctorEvidence).where(ProctorEvidence.blob_path == slot.blob_path)
            )
        ).one()
    assert linked.proctor_event_id is not None


# Finding 9: the server's clock on a row it adopted.


async def test_a_later_phase_cannot_shorten_an_event_the_server_confirmed(
    world: World, app_db: Database
) -> None:
    await world.open()
    await world.beat()
    first = item(
        1, "CAMERA_DISCONNECTED", source="camera", details={"phase": "started"}, duration_ms=0
    )
    await world.send(first)
    world.clock.advance(2)
    await world.beat(camera="off")
    for _ in range(3):
        world.clock.advance(4)
        await world.beat(camera="off")
        await world.tick()
    world.clock.advance(20)
    await world.beat(camera="off")
    await world.tick()
    (event,) = await rows(app_db, world, ProctorEvent.event == "CAMERA_DISCONNECTED")
    assert event.details.get("server_confirmed") and (event.duration_ms or 0) >= 20_000
    short = item(
        2, "CAMERA_DISCONNECTED", source="camera", details={"phase": "ended"}, duration_ms=3000
    )
    await world.send(short)
    (event,) = await rows(app_db, world, ProctorEvent.event == "CAMERA_DISCONNECTED")
    assert (event.duration_ms or 0) >= 20_000


# Findings 6 and the unwritten ones: the Conductor's summary goes through the outbox, and
# server-raised events carry the server's references.


async def test_a_raised_event_is_handed_to_the_outbox_for_the_interviews_summary(
    world: World, app_db: Database
) -> None:
    await world.open()
    await world.send(item(1, "PHONE_DETECTED"), item(2, "VM_DETECTED", at=1))
    async with app_db.tenant(world.org) as session:
        noted = (
            await session.scalars(select(OutboxEvent).where(OutboxEvent.topic == "proctor.noted"))
        ).all()
    assert [(n.payload["kind"], n.payload["severity"]) for n in noted] == [
        ("phone_detected", "critical")
    ]
    assert noted[0].payload["interview_id"] == str(world.interview)


async def test_the_outbox_consumer_tells_the_conductor_and_lets_a_refusal_retry(
    world: World,
) -> None:
    from hirevion_core.access.errors import Conflict
    from hirevion_core.proctoring.watcher import handle_noted

    calls: list[tuple[Any, ...]] = []
    busy = [True]

    class FakeConductor:
        async def note_proctor_event(self, *args: Any) -> None:
            if busy[0]:
                busy[0] = False
                raise Conflict("turn-in-progress", "Another turn is still being handled")
            calls.append(args)

    payload = {
        "interview_id": str(world.interview),
        "kind": "phone_detected",
        "severity": "critical",
    }
    with pytest.raises(Conflict):
        await handle_noted(FakeConductor(), world.org, payload)  # type: ignore[arg-type]
    await handle_noted(FakeConductor(), world.org, payload)  # type: ignore[arg-type]
    assert calls == [(world.org, world.interview, "phone_detected", "critical")]


async def test_events_the_server_raised_carry_references_to_the_recording(
    world: World, app_db: Database, admin_engine: Any
) -> None:
    policy = {"recording": {"screen": True, "camera": True}}
    await set_interview(admin_engine, world, policy=json.dumps(policy))
    await world.open()
    await world.beat()
    await world.engine.observe(world.org, world.interview, "camera", "livekit", "down", T0)
    world.clock.advance(30)
    await world.beat()
    await world.tick()
    (down,) = await rows(app_db, world, ProctorEvent.event == "CAMERA_DISCONNECTED")
    assert down.severity == "CRITICAL"
    async with app_db.tenant(world.org) as session:
        evidence = (
            await session.scalars(
                select(ProctorEvidence).where(
                    ProctorEvidence.proctor_event_id == down.id, ProctorEvidence.origin == "server"
                )
            )
        ).all()
    assert {"screen_segment", "camera_segment"} <= {e.kind for e in evidence}
    _ = (UUID, datetime, text)
