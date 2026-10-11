"""The proctoring engine against the database (SP-14): the session and its pinned policy,
idempotent and gap-tracked batches, episodes, severity, evidence, heartbeats, what the server
observes, nudges and the alerts on the realtime stream."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.access.errors import Conflict, Invalid
from hirevion_core.db.session import Database
from hirevion_core.interview_session import realtime
from hirevion_core.interview_session.conductor import hot_key
from hirevion_core.models import ProctorEvent, ProctorEvidence, ProctorSession
from hirevion_core.proctoring import nudges
from hirevion_core.proctoring.normaliser import Incoming
from hirevion_core.proctoring.service import ProctorEngine

from .test_interviews_schema import insert_interview

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]
T0 = datetime(2026, 10, 12, 5, 0, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> datetime:
        self.now += timedelta(seconds=seconds)
        return self.now


class FakeUploads:
    def __init__(self) -> None:
        self.paths: list[str] = []

    def upload_url(
        self, organization_id: UUID, path: Any, expires: timedelta = timedelta(0)
    ) -> str:
        self.paths.append(str(path))
        return f"https://storage.example/{path}?sig=1&ttl={int(expires.total_seconds())}"


def item(seq: int, event: str = "FACE_ABSENT", *, at: float = 0, **fields: Any) -> Incoming:
    source = {"FACE_ABSENT": "camera", "PHONE_DETECTED": "camera", "MULTIPLE_FACES": "camera"}
    return Incoming(
        seq=seq,
        event=event,
        source=fields.pop("source", source.get(event, "native")),
        started_at=T0 + timedelta(seconds=at),
        **fields,
    )


class World:
    def __init__(self, org: UUID, interview: UUID, engine: ProctorEngine, clock: Clock) -> None:
        self.org, self.interview, self.engine, self.clock = org, interview, engine, clock
        self.session_id: UUID | None = None

    async def open(self) -> UUID:
        opened = await self.engine.open_session(self.org, self.interview, "1.4.0")
        self.session_id = opened.proctor_session_id
        return opened.proctor_session_id

    async def send(self, *items: Incoming) -> Any:
        assert self.session_id is not None
        return await self.engine.ingest(self.org, self.interview, self.session_id, list(items))

    async def beat(self, **status: Any) -> Any:
        assert self.session_id is not None
        body = {
            "camera": "on",
            "mic": "on",
            "screen": "capturing",
            "third_eye": "not_required",
            "displays": 1,
            "seq_high": 0,
            **status,
        }
        return await self.engine.heartbeat(self.org, self.interview, self.session_id, body)

    async def tick(self) -> None:
        assert self.session_id is not None
        await self.engine.tick(self.org, self.session_id)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
async def world(
    app_db: Database,
    valkey: Redis,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring: Any,
    clock: Clock,
) -> World:
    org = await make_organization("Acme")
    interview = await insert_interview(admin_engine, await make_hiring(org), status="in_progress")
    return World(org, interview, ProctorEngine(app_db, valkey, clock=clock), clock)


async def rows(db: Database, world: World, *where: Any) -> list[ProctorEvent]:
    async with db.tenant(world.org) as session:
        found = await session.scalars(
            select(ProctorEvent).where(*where).order_by(ProctorEvent.started_at, ProctorEvent.seq)
        )
        return list(found.all())


async def set_interview(admin_engine: AsyncEngine, world: World, **columns: Any) -> None:
    sets = ", ".join(f"{name} = :{name}" for name in columns)
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(f"UPDATE interviews SET {sets} WHERE id = :id"),  # noqa: S608 (test columns)
            {**columns, "id": world.interview},
        )


# The session and its policy.


async def test_a_session_opens_once_and_pins_the_policy(world: World, app_db: Database) -> None:
    first = await world.engine.open_session(world.org, world.interview, "1.4.0")
    again = await world.engine.open_session(world.org, world.interview, "1.4.1")
    assert again.proctor_session_id == first.proctor_session_id
    view = first.view()
    assert view["level"] == "standard" and view["checks"] == [
        "face",
        "focus",
        "gaze",
        "phone",
        "processes",
        "displays",
    ]
    assert view["thresholds"]["FACE_ABSENT"] == {"warn_after_ms": 5000, "critical_after_ms": 30000}
    assert view["heartbeat_seconds"] == 5 and view["batch_max_events"] == 100
    assert view["acked_through"] == 0 and view["single_display"] is False
    blocked = view["app_rules"]["blocked"]
    assert len(blocked) >= 30 and {"match", "value", "category"} <= set(blocked[0])
    assert all(rule["match"] != "name" or rule["with"] for rule in blocked)
    async with app_db.tenant(world.org) as session:
        row = await session.get_one(ProctorSession, first.proctor_session_id)
    assert row.policy_version == 1 and row.app_version == "1.4.1"


async def test_the_policy_follows_the_interviews_snapshot(
    world: World, admin_engine: AsyncEngine
) -> None:
    policy = {
        "proctoring_level": "strict",
        "third_eye": "required",
        "accommodations": ["relaxed_gaze", "assistive_technology"],
        "recording": {"screen": True, "camera": True},
    }
    await set_interview(admin_engine, world, policy=json.dumps(policy))
    view = (await world.engine.open_session(world.org, world.interview, "1.4.0")).view()
    assert view["level"] == "strict" and "audio" in view["checks"] and view["single_display"]
    assert view["thresholds"]["THIRD_EYE_DISCONNECTED"]["critical_after_ms"] == 60_000
    assert "GAZE_DEVIATION" not in view["thresholds"]
    assert view["accommodations"] == ["assistive_technology", "relaxed_gaze"]
    assert {"match": "path", "value": "C:\\Windows\\System32\\Narrator.exe"} in view["app_rules"][
        "allowed"
    ]


async def test_a_session_needs_a_running_interview(world: World, admin_engine: AsyncEngine) -> None:
    await set_interview(admin_engine, world, status="invited")
    with pytest.raises(Conflict) as early:
        await world.engine.open_session(world.org, world.interview, "1.4.0")
    assert early.value.code == "interview-not-open"
    await set_interview(admin_engine, world, status="completed")
    with pytest.raises(Conflict) as late:
        await world.engine.open_session(world.org, world.interview, "1.4.0")
    assert late.value.code == "proctor-session-closed"


# Events.


async def test_batches_are_idempotent_and_track_gaps(world: World, app_db: Database) -> None:
    await world.open()
    ack = await world.send(item(1), item(2, "WINDOW_MINIMIZED", at=1, duration_ms=4000))
    assert (ack.acked_through, ack.missing) == (2, [])
    gap = await world.send(item(5, "PHONE_DETECTED", at=2))
    assert (gap.acked_through, gap.missing) == (2, [3, 4])
    retry = await world.send(item(1), item(2, "WINDOW_MINIMIZED", at=1), item(5, "PHONE_DETECTED"))
    assert (retry.acked_through, retry.missing) == (2, [3, 4])
    stored = await rows(app_db, world)
    assert sorted(r.seq or 0 for r in stored if r.origin == "client") == [1, 2, 5]
    gaps = [r for r in stored if r.event == "TELEMETRY_GAP"]
    assert len(gaps) == 1 and gaps[0].details["from_seq"] == 3 and gaps[0].details["to_seq"] == 4
    assert gaps[0].severity == "WARNING" and gaps[0].origin == "server"
    filled = await world.send(item(4, at=3), item(3, at=3))
    assert (filled.acked_through, filled.missing) == (5, [])


async def test_a_batch_with_an_unknown_event_is_refused_whole(
    world: World, app_db: Database
) -> None:
    await world.open()
    with pytest.raises(Invalid) as refused:
        await world.send(item(1), item(2, "MAKE_COFFEE"))
    assert refused.value.code == "unknown-event"
    assert await rows(app_db, world) == []
    with pytest.raises(Invalid) as wild:
        await world.send(item(10**9))
    assert wild.value.code == "seq-out-of-range"


async def test_severity_comes_from_the_policy_and_keys_are_never_stored(
    world: World, app_db: Database
) -> None:
    await world.open()
    await world.send(
        item(1, "FACE_ABSENT", duration_ms=31_000, details={"keys": "secret", "frames": 12}),
        item(2, "APPLICATION_FOCUS_CHANGE", at=1, duration_ms=2000, details={"text": "typed"}),
        item(3, "PHONE_DETECTED", at=2, details={"severity_hint": "info"}),
    )
    face, focus, phone = await rows(app_db, world)
    assert (face.severity, focus.severity, phone.severity) == ("CRITICAL", "INFO", "CRITICAL")
    assert face.details["frames"] == 12 and "keys" not in face.details
    assert "text" not in focus.details
    assert phone.details["server"]["severity_hint"] == "INFO"
    assert face.policy_version == 1 and face.confidence is None


async def test_the_three_phases_of_an_episode_are_one_event_updated_in_place(
    world: World, app_db: Database, valkey: Redis
) -> None:
    await world.open()
    start = item(1, details={"phase": "started"}, duration_ms=0)
    mid = item(2, details={"phase": "escalated", "level": 1}, duration_ms=6000)
    end = item(3, details={"phase": "ended", "max_faces": 1}, duration_ms=31_000)
    await world.send(start)
    await world.send(mid)
    await world.send(end)
    await world.send(mid, start)  # a retry, out of order
    (episode,) = await rows(app_db, world)
    assert episode.phase == "ended" and episode.duration_ms == 31_000 and not episode.ongoing
    assert episode.severity == "CRITICAL" and episode.last_seq == 3 and episode.seq == 1
    assert episode.details["level"] == 1 and episode.details["max_faces"] == 1
    sent = await realtime.read(valkey, world.interview, "0")
    alerts = [e for e in sent if e.type == "PROCTOR_EVENT"]
    assert [a.data["change"] for a in alerts] == ["created", "updated", "updated"]
    assert {a.data["id"] for a in alerts} == {str(episode.id)}


async def test_a_repeated_warning_escalates(world: World, app_db: Database) -> None:
    await world.open()
    await world.send(
        *(item(n, "WINDOW_MINIMIZED", at=n * 10, duration_ms=4000) for n in range(1, 6))
    )
    severities = [r.severity for r in await rows(app_db, world)]
    assert severities == ["WARNING"] * 4 + ["CRITICAL"]


async def test_events_reach_the_realtime_stream_and_the_nudge_reaches_the_candidate(
    world: World, valkey: Redis
) -> None:
    await world.open()
    await world.send(item(1, "PHONE_DETECTED"))
    await world.send(item(2, "PHONE_DETECTED", at=1))  # inside the cooldown
    events = await realtime.read(valkey, world.interview, "0")
    alerts = [e for e in events if e.type == "PROCTOR_EVENT"]
    assert len(alerts) == 2 and alerts[0].data["severity"] == "CRITICAL"
    assert (
        alerts[0].data["event"] == "PHONE_DETECTED" and alerts[0].data["review_status"] == "pending"
    )
    notices = await nudges.read(valkey, world.interview, "0")
    assert len(notices) == 1 and notices[0][1]["kind"] == "phone_detected"
    hot = await valkey.hget(hot_key(world.interview), "notice")
    assert json.loads(hot)["kind"] == "phone_detected"


async def test_the_policy_can_turn_nudges_off(
    world: World, admin_engine: AsyncEngine, valkey: Redis
) -> None:
    policy = {"proctoring": {"nudges": {"enabled": False}}}
    await set_interview(admin_engine, world, policy=json.dumps(policy))
    await world.open()
    await world.send(item(1, "PHONE_DETECTED"))
    assert await nudges.read(valkey, world.interview, "0") == []


async def test_level_off_acknowledges_but_stores_nothing(
    world: World, admin_engine: AsyncEngine, app_db: Database
) -> None:
    await set_interview(admin_engine, world, policy=json.dumps({"proctoring_level": "off"}))
    await world.open()
    ack = await world.send(item(1, "PHONE_DETECTED"), item(2))
    assert ack.acked_through == 2
    assert await rows(app_db, world) == []


async def test_events_are_taken_for_a_while_after_the_interview_but_heartbeats_are_not(
    world: World, admin_engine: AsyncEngine
) -> None:
    await world.open()
    ended = T0 + timedelta(seconds=1)
    await set_interview(admin_engine, world, status="completed", ended_at=ended, completed_at=ended)
    world.clock.advance(120)
    assert (await world.send(item(1, "PHONE_DETECTED"))).acked_through == 1
    with pytest.raises(Conflict) as heartbeat:
        await world.beat()
    assert heartbeat.value.code == "proctor-session-closed"
    world.clock.advance(15 * 60)
    with pytest.raises(Conflict) as late:
        await world.send(item(2))
    assert late.value.code == "proctor-session-closed"


# Evidence.


async def test_snapshots_get_a_write_only_slot_and_are_linked_once(
    world: World, app_db: Database
) -> None:
    await world.open()
    storage = FakeUploads()
    digest = "a" * 64

    async def slot(**changes: Any) -> Any:
        assert world.session_id is not None
        body = {
            "kind": "screen",
            "seq": 1,
            "content_type": "image/jpeg",
            "size": 84_213,
            "sha256": digest,
            **changes,
        }
        return await world.engine.evidence_upload(
            world.org, world.interview, world.session_id, storage, **body
        )

    one = await slot()
    assert one.blob_path.endswith(f"/interviews/{world.interview}/evidence/1-screen.jpg")
    assert one.headers == {"x-ms-blob-type": "BlockBlob"} and "ttl=300" in one.upload_url
    assert (await slot()).blob_path == one.blob_path  # a retry
    with pytest.raises(Conflict) as other:
        await slot(sha256="b" * 64)
    assert other.value.code == "evidence-locked"
    for bad in ({"content_type": "text/html"}, {"kind": "disk"}, {"sha256": "xyz"}):
        with pytest.raises(Invalid):
            await slot(**bad)

    await world.send(
        item(
            1,
            "BLOCKED_PROCESS_DETECTED",
            evidence=[
                {"type": "snapshot", "blob_path": one.blob_path},
                {
                    "type": "snapshot",
                    "blob_path": f"{world.org}/interviews/{world.interview}/evidence/9-screen.jpg",
                },
            ],
            details={
                "name": "anydesk.exe",
                "publisher": "philandro Software GmbH",
                "category": "remote_access",
            },
        )
    )
    async with app_db.tenant(world.org) as session:
        (event,) = (await session.scalars(select(ProctorEvent))).all()
        evidence = (await session.scalars(select(ProctorEvidence))).all()
    assert event.details["server"]["rejected_evidence"][0].endswith("9-screen.jpg")
    linked = [e for e in evidence if e.origin == "client"]
    assert [e.proctor_event_id for e in linked] == [event.id] and linked[0].kind == "screenshot"
    assert "process_metadata" in {e.kind for e in evidence if e.origin == "server"}
    with pytest.raises(Conflict):
        await slot()  # claimed: it can't be given out again


# Heartbeats and what the server observes.


async def test_a_device_the_server_sees_down_becomes_an_event_that_grows_and_closes(
    world: World, app_db: Database
) -> None:
    await world.open()
    await world.beat()
    world.clock.advance(5)
    await world.beat(camera="off")
    await world.tick()
    assert await rows(app_db, world) == []  # inside the debounce
    world.clock.advance(5)
    await world.beat(camera="off")
    await world.tick()
    (down,) = await rows(app_db, world)
    assert down.event == "CAMERA_DISCONNECTED" and down.origin == "server" and down.ongoing
    assert down.severity == "WARNING" and down.seq is None
    world.clock.advance(6)
    await world.beat(camera="off")
    await world.tick()
    (down,) = await rows(app_db, world)
    assert down.severity == "CRITICAL"
    world.clock.advance(2)
    await world.beat(camera="on")
    await world.tick()
    down, back = await rows(app_db, world)
    assert not down.ongoing and 12_000 <= (down.duration_ms or 0) <= 14_000
    assert back.event == "CAMERA_RECONNECTED" and back.severity == "INFO"


async def test_the_devices_own_report_of_a_disconnection_joins_the_servers_sighting(
    world: World, app_db: Database
) -> None:
    await world.open()
    await world.beat(mic="off")
    world.clock.advance(6)
    await world.beat(mic="off")
    await world.tick()
    world.clock.advance(1)
    await world.send(item(1, "MIC_DISCONNECTED", at=5, duration_ms=3000, source="audio"))
    (event,) = await rows(app_db, world)
    assert event.origin == "server" and event.details["client_reported"] is True


async def test_a_flap_inside_the_debounce_raises_nothing(world: World, app_db: Database) -> None:
    await world.open()
    await world.beat(screen="stopped")
    world.clock.advance(2)
    await world.beat(screen="capturing")
    world.clock.advance(5)
    await world.tick()
    assert await rows(app_db, world) == []


async def test_missed_heartbeats_raise_a_telemetry_gap_that_closes_when_they_resume(
    world: World, app_db: Database
) -> None:
    await world.open()
    await world.beat()
    world.clock.advance(10)
    await world.tick()
    assert await rows(app_db, world) == []
    world.clock.advance(15)
    await world.tick()
    (gap,) = await rows(app_db, world)
    assert gap.event == "TELEMETRY_GAP" and gap.ongoing and gap.severity == "WARNING"
    assert gap.started_at == T0  # from the last heartbeat
    world.clock.advance(20)
    await world.beat()
    await world.tick()
    (gap,) = await rows(app_db, world)
    assert not gap.ongoing and 44_000 <= (gap.duration_ms or 0) <= 46_000


async def test_a_session_that_never_sends_a_heartbeat_is_a_gap_from_its_opening(
    world: World, app_db: Database
) -> None:
    await world.open()
    world.clock.advance(30)
    await world.tick()
    (gap,) = await rows(app_db, world)
    assert gap.event == "TELEMETRY_GAP" and gap.started_at == T0


async def test_an_interruption_pauses_the_watch_and_a_return_resumes_it(
    world: World, app_db: Database, admin_engine: AsyncEngine
) -> None:
    await world.open()
    await world.beat()
    await set_interview(admin_engine, world, status="interrupted")
    world.clock.advance(60)
    await world.tick()
    world.clock.advance(60)
    await world.tick()
    assert [r.event for r in await rows(app_db, world)] == ["SESSION_INTERRUPTED"]
    await set_interview(admin_engine, world, status="in_progress")
    world.clock.advance(5)
    await world.tick()
    world.clock.advance(5)
    await world.tick()
    events = [r.event for r in await rows(app_db, world)]
    assert events == ["SESSION_INTERRUPTED", "SESSION_RESUMED"]


async def test_the_watcher_closes_the_session_with_the_interview(
    world: World, app_db: Database, admin_engine: AsyncEngine
) -> None:
    await world.open()
    await world.beat()
    await set_interview(admin_engine, world, status="completed")
    world.clock.advance(60)
    await world.tick()
    async with app_db.tenant(world.org) as session:
        row = await session.get_one(ProctorSession, world.session_id)
    assert row.status == "closed" and row.closed_at is not None and row.watch_at is None
    assert await rows(app_db, world) == []  # no gap for the silence after the end


async def test_a_recording_gap_is_an_event_of_its_own_length(
    world: World, app_db: Database
) -> None:
    await world.open()
    start = T0 + timedelta(seconds=30)
    assert await world.engine.record_gap(world.org, world.interview, "screen-1", start, 45_000)
    assert await world.engine.record_gap(world.org, world.interview, "camera", start, 2_000)
    gap, loss = await rows(app_db, world)
    assert gap.event == "SCREEN_CAPTURE_STOPPED" and gap.severity == "CRITICAL"
    assert (
        gap.duration_ms == 45_000 and not gap.ongoing and gap.details["reason"] == "recording_gap"
    )
    assert loss.event == "TELEMETRY_GAP" and loss.severity == "WARNING"
    assert loss.details["recording_gap"]["track"] == "camera"
    # The same screen gap reported again changes nothing but its note.
    await world.engine.record_gap(world.org, world.interview, "screen-1", start, 45_000)
    assert len(await rows(app_db, world)) == 2


async def test_recording_gap_events_of_the_upload_service_are_read(
    world: World, app_db: Database
) -> None:
    from hirevion_core.proctoring.watcher import handle_gap

    await world.open()
    await world.beat()
    start = world.clock.now

    def payload(**fields: Any) -> dict[str, Any]:
        return {
            "interview_id": str(world.interview),
            "track": "screen-1",
            "kind": "stalled",
            "state": "open",
            "from_seq": 4,
            "to_seq": None,
            "from_time": start.isoformat(),
            "to_time": None,
            **fields,
        }

    # A stall that lasts is an event that grows; one that ends is closed.
    await handle_gap(world.engine, world.org, payload())
    world.clock.advance(40)
    await world.beat()
    await world.tick()
    (stall,) = await rows(app_db, world)
    assert (
        stall.event == "SCREEN_CAPTURE_STOPPED" and stall.ongoing and stall.severity == "CRITICAL"
    )
    assert stall.details["sources"] == ["upload:screen-1"]
    end = world.clock.now
    await handle_gap(
        world.engine, world.org, payload(state="closed", to_seq=6, to_time=end.isoformat())
    )
    world.clock.advance(1)
    await world.beat()
    await world.tick()
    (stall,) = await rows(app_db, world)
    assert not stall.ongoing and 39_000 <= (stall.duration_ms or 0) <= 42_000
    # A hole found at assembly is a finished event of the hole's length.
    hole = payload(
        track="mic",
        kind="missing",
        state="closed",
        from_seq=9,
        to_seq=12,
        from_time=(start + timedelta(seconds=100)).isoformat(),
        to_time=(start + timedelta(seconds=140)).isoformat(),
    )
    await handle_gap(world.engine, world.org, hole)
    events = await rows(app_db, world)
    gap = next(r for r in events if r.event == "TELEMETRY_GAP" and r.details.get("reason"))
    assert gap.duration_ms == 40_000 and gap.details["recording_gap"]["kind"] == "missing"
    # Kinds this engine doesn't know are left alone.
    await handle_gap(world.engine, world.org, payload(kind="skipped"))
    assert len(await rows(app_db, world)) == len(events)


async def test_livekit_sightings_are_votes_the_watcher_acts_on(
    world: World, app_db: Database
) -> None:
    await world.open()
    await world.beat()
    down_at = world.clock.now
    await world.engine.observe(world.org, world.interview, "screen", "livekit", "down", down_at)
    world.clock.advance(6)
    # The desktop still says it is capturing; LiveKit's view stands.
    await world.beat(screen="capturing")
    await world.tick()
    (event,) = await rows(app_db, world)
    assert event.event == "SCREEN_CAPTURE_STOPPED" and event.details["sources"] == ["livekit"]
    await world.engine.observe(
        world.org, world.interview, "screen", "livekit", "up", world.clock.now
    )
    world.clock.advance(1)
    await world.tick()
    (event,) = await rows(app_db, world)
    assert not event.ongoing
