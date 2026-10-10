"""The media worker (SP-12 Task 5): assembling a track's acknowledged segments into one file and
a timeline map, with ffmpeg as a separate process (here a fake; the real one is exercised in
`test_ffmpeg_integration.py` when it is installed)."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.db.session import Database
from hirevion_core.interview_session import realtime
from hirevion_core.models import Recording
from hirevion_core.recordings import segments as segment_service
from hirevion_core.recordings import tracks
from hirevion_core.recordings.assembly import Assembler
from hirevion_core.recordings.ffmpeg import FfmpegError
from hirevion_core.recordings.settings import RecordingSettings
from hirevion_core.recordings.worker import handle_interview_ended
from hirevion_core.storage.paths import BlobPath

from .test_interviews_schema import insert_interview
from .test_recordings_schema import recording, segment

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]
T0 = datetime(2026, 10, 12, 5, 0, 0, tzinfo=UTC)
NOW = datetime.now(UTC).replace(microsecond=0)


class FakeStore:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.types: dict[str, str] = {}

    async def digest(self, path: BlobPath) -> tuple[int, str] | None:
        data = self.blobs.get(str(path))
        return None if data is None else (len(data), hashlib.sha256(data).hexdigest())

    async def download_to(self, path: BlobPath, destination: Path) -> None:
        if str(path) not in self.blobs:
            raise FileNotFoundError(str(path))
        destination.write_bytes(self.blobs[str(path)])

    async def upload_file(self, path: BlobPath, source: Path, content_type: str) -> None:
        self.blobs[str(path)] = source.read_bytes()
        self.types[str(path)] = content_type

    async def put(self, path: BlobPath, data: bytes, content_type: str) -> None:
        self.blobs[str(path)] = data
        self.types[str(path)] = content_type


class FakeFfmpeg:
    """Joins the files byte for byte, the way `-c copy` joins whole segments."""

    path = "fake-ffmpeg"

    def __init__(self, *, installed: bool = True, failures: int = 0) -> None:
        self.installed = installed
        self.failures = failures
        self.calls: list[tuple[list[str], str, str]] = []

    def available(self) -> bool:
        return self.installed

    async def concat(
        self, workdir: Path, names: Sequence[str], output: str, container: str
    ) -> None:
        self.calls.append((list(names), output, container))
        if self.failures:
            self.failures -= 1
            raise FfmpegError("ffmpeg exited with 1: Invalid data found")
        (workdir / output).write_bytes(b"".join((workdir / n).read_bytes() for n in names))


def payload(track: str, seq: int) -> bytes:
    return f"{track}#{seq};".encode()


async def completed_interview(
    admin_engine: AsyncEngine, org: UUID, make_hiring: Any, *, status: str = "completed"
) -> UUID:
    return await insert_interview(admin_engine, await make_hiring(org), status=status)


async def add_segments(
    app_db: Database,
    store: FakeStore,
    org: UUID,
    interview: UUID,
    track: str,
    seqs: Sequence[int],
    *,
    container: str = "mp4",
    codec: str = "h264",
    state: str = "acknowledged",
    requested_at: datetime | None = None,
    tamper: Sequence[int] = (),
) -> None:
    """Segments `seq` of `track`, each 10 s long and starting at `seq * 10` s, stored in `store`."""
    async with app_db.tenant(org) as session:
        for seq in seqs:
            data = payload(track, seq)
            name = tracks.segment_filename(track, seq, container)
            path = f"{org}/interviews/{interview}/{tracks.folder(track)}/{name}"
            stored = b"tampered" if seq in tamper else data
            store.blobs[path] = stored
            session.add(
                segment(
                    org,
                    interview,
                    track=track,
                    seq=seq,
                    started_at=T0 + timedelta(seconds=seq * 10),
                    bytes=len(data),
                    sha256=hashlib.sha256(data).hexdigest(),
                    container=container,
                    codec=codec,
                    blob_path=path,
                    state=state,
                    **({"requested_at": requested_at} if requested_at else {}),
                )
            )
        session.add(
            recording(
                org,
                interview,
                track=track,
                first_seq=min(seqs),
                last_seq=max(seqs),
            )
        )


def assembler(
    app_db: Database,
    store: FakeStore,
    ffmpeg: FakeFfmpeg | None = None,
    redis: Redis | None = None,
    **settings: Any,
) -> tuple[Assembler, FakeFfmpeg]:
    ffmpeg = ffmpeg or FakeFfmpeg()
    return Assembler(app_db, store, ffmpeg, RecordingSettings(**settings), redis), ffmpeg


async def load(app_db: Database, org: UUID, interview: UUID, track: str) -> Recording:
    async with app_db.tenant(org) as session:
        row = await session.scalar(
            select(Recording).where(Recording.interview_id == interview, Recording.track == track)
        )
    assert row is not None
    return row


async def test_a_finished_interviews_tracks_become_one_file_each_with_a_timeline(
    app_db: Database,
    admin_engine: AsyncEngine,
    valkey: Redis,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    org = await make_organization("Acme")
    interview = await completed_interview(admin_engine, org, make_hiring)
    store = FakeStore()
    await add_segments(app_db, store, org, interview, "screen-1", [0, 1, 3])  # 2 never came
    await add_segments(
        app_db, store, org, interview, "mic", [0, 1, 2], container="webm", codec="opus"
    )
    worker, ffmpeg = assembler(app_db, store, redis=valkey)
    assert await worker.assemble_interview(org, interview, NOW) == 2

    screen = await load(app_db, org, interview, "screen-1")
    assert screen.status == "assembled" and screen.container == "mp4"
    assert screen.blob_path == f"{org}/interviews/{interview}/screen/screen-1-full.mp4"
    assert screen.timeline_path == f"{org}/interviews/{interview}/screen/screen-1-timeline.json"
    expected = b"".join(payload("screen-1", n) for n in (0, 1, 3))
    assert store.blobs[screen.blob_path] == expected
    assert (screen.assembled_bytes, screen.assembled_sha256) == (
        len(expected),
        hashlib.sha256(expected).hexdigest(),
    )
    assert screen.duration_ms == 30_000
    assert [(g["from_seq"], g["to_seq"], g["reason"]) for g in screen.gaps] == [(2, 2, "missing")]
    assert store.types[screen.blob_path] == "video/mp4"

    timeline = json.loads(store.blobs[screen.timeline_path])
    assert [(s["seq"], s["file_offset_ms"]) for s in timeline["segments"]] == [
        (0, 0),
        (1, 10_000),
        (3, 20_000),
    ]
    assert timeline["segments"][2]["started_at"] == (T0 + timedelta(seconds=30)).isoformat()
    assert timeline["gaps"][0]["from_time"] == (T0 + timedelta(seconds=20)).isoformat()

    mic = await load(app_db, org, interview, "mic")
    assert mic.blob_path == f"{org}/interviews/{interview}/audio/mic-full.webm"  # §85's audio/
    assert store.types[mic.blob_path] == "audio/webm"
    assert mic.gaps == []
    # ffmpeg got relative names in order, and the container to copy into.
    assert ffmpeg.calls[0] == (
        ["seg-000000.mp4", "seg-000001.mp4", "seg-000002.mp4"],
        "assembled.mp4",
        "mp4",
    )
    live = await realtime.read(valkey, interview)
    assert sorted((e.data["track"], e.data["status"]) for e in live) == [
        ("mic", "assembled"),
        ("screen-1", "assembled"),
    ]


async def test_assembling_twice_changes_nothing(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    org = await make_organization("Acme")
    interview = await completed_interview(admin_engine, org, make_hiring)
    store = FakeStore()
    await add_segments(
        app_db, store, org, interview, "camera", [0, 1], container="webm", codec="vp8"
    )
    worker, ffmpeg = assembler(app_db, store)
    assert await worker.assemble_interview(org, interview, NOW) == 1
    assert await worker.assemble_interview(org, interview, NOW) == 0
    assert len(ffmpeg.calls) == 1


async def test_a_segment_that_changed_after_its_acknowledgement_is_left_out(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    org = await make_organization("Acme")
    interview = await completed_interview(admin_engine, org, make_hiring)
    store = FakeStore()
    await add_segments(app_db, store, org, interview, "screen-1", [0, 1, 2, 3], tamper=[2])
    worker, _ = assembler(app_db, store)
    await worker.assemble_interview(org, interview, NOW)
    row = await load(app_db, org, interview, "screen-1")
    assert row.status == "assembled"
    assert store.blobs[row.blob_path] == b"".join(payload("screen-1", n) for n in (0, 1, 3))
    assert [(g["from_seq"], g["to_seq"], g["reason"]) for g in row.gaps] == [(2, 2, "corrupt")]


async def test_nothing_is_built_while_the_interview_is_still_going(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    org = await make_organization("Acme")
    interview = await completed_interview(admin_engine, org, make_hiring, status="in_progress")
    store = FakeStore()
    await add_segments(app_db, store, org, interview, "camera", [0], container="webm", codec="vp8")
    worker, ffmpeg = assembler(app_db, store)
    assert await worker.assemble_interview(org, interview, NOW) == 0
    assert ffmpeg.calls == []
    assert (await load(app_db, org, interview, "camera")).status == "recording"


async def test_segments_still_arriving_are_waited_for_and_then_counted_missing(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    org = await make_organization("Acme")
    interview = await completed_interview(admin_engine, org, make_hiring)
    store = FakeStore()
    await add_segments(app_db, store, org, interview, "screen-1", [0, 1])
    async with app_db.tenant(org) as session:
        session.add(  # a URL was asked for a minute ago and nothing has come of it
            segment(
                org,
                interview,
                seq=2,
                requested_at=NOW - timedelta(seconds=60),
                started_at=T0 + timedelta(seconds=20),
                state="requested",
            )
        )
    worker, ffmpeg = assembler(app_db, store, recording_settle_seconds=120)
    assert await worker.assemble_interview(org, interview, NOW) == 0
    waiting = await load(app_db, org, interview, "screen-1")
    assert (waiting.status, waiting.note) == ("assembly-pending", "waiting-for-uploads")
    assert ffmpeg.calls == []

    assert await worker.assemble_interview(org, interview, NOW + timedelta(seconds=90)) == 1
    done = await load(app_db, org, interview, "screen-1")
    assert done.status == "assembled" and done.duration_ms == 20_000


async def test_without_ffmpeg_tracks_wait_and_the_worker_says_so_once(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    org = await make_organization("Acme")
    interview = await completed_interview(admin_engine, org, make_hiring)
    store = FakeStore()
    await add_segments(app_db, store, org, interview, "screen-1", [0, 1])
    worker, ffmpeg = assembler(app_db, store, FakeFfmpeg(installed=False))
    with caplog.at_level(logging.WARNING):
        assert await worker.assemble_interview(org, interview, NOW) == 0
        assert await worker.assemble_interview(org, interview, NOW) == 0
    row = await load(app_db, org, interview, "screen-1")
    assert (row.status, row.note) == ("assembly-pending", "ffmpeg-missing")
    assert row.next_attempt_at is not None and row.next_attempt_at > NOW  # not retried at once
    assert ffmpeg.calls == []
    assert [r.getMessage() for r in caplog.records].count(
        "ffmpeg isn't installed (HV_FFMPEG_PATH='fake-ffmpeg'): recordings stay assembly-pending"
    ) == 1
    # Once it is installed, the next pass builds the track.
    ffmpeg.installed = True
    assert await worker.assemble_interview(org, interview, NOW + timedelta(minutes=11)) == 1
    assert (await load(app_db, org, interview, "screen-1")).status == "assembled"


async def test_a_failure_backs_off_and_eventually_fails_the_track(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    org = await make_organization("Acme")
    interview = await completed_interview(admin_engine, org, make_hiring)
    store = FakeStore()
    await add_segments(app_db, store, org, interview, "screen-1", [0, 1])
    worker, _ = assembler(app_db, store, FakeFfmpeg(failures=99), recording_assembly_attempts=3)
    moment = NOW
    for attempt in (1, 2):
        assert await worker.assemble_interview(org, interview, moment) == 0
        row = await load(app_db, org, interview, "screen-1")
        assert (row.status, row.attempts) == ("assembly-pending", attempt)
        assert row.note is not None and "Invalid data" in row.note
        assert row.next_attempt_at is not None and row.next_attempt_at > moment
        # Backing off: asking again straight away does nothing.
        assert await worker.assemble_interview(org, interview, moment) == 0
        assert (await load(app_db, org, interview, "screen-1")).attempts == attempt
        moment = row.next_attempt_at
    await worker.assemble_interview(org, interview, moment)
    failed = await load(app_db, org, interview, "screen-1")
    assert (failed.status, failed.attempts) == ("failed", 3)


async def test_a_track_with_nothing_acknowledged_fails_with_a_reason(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    org = await make_organization("Acme")
    interview = await completed_interview(admin_engine, org, make_hiring)
    store = FakeStore()
    await add_segments(
        app_db,
        store,
        org,
        interview,
        "camera",
        [0],
        container="webm",
        codec="vp8",
        state="uploaded",
        requested_at=NOW - timedelta(hours=1),
    )
    worker, _ = assembler(app_db, store)
    await worker.assemble_interview(org, interview, NOW)
    row = await load(app_db, org, interview, "camera")
    assert (row.status, row.note) == ("failed", "no acknowledged segments")


async def test_a_segment_acknowledged_after_assembly_has_the_track_built_again(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    org = await make_organization("Acme")
    interview = await completed_interview(admin_engine, org, make_hiring)
    store = FakeStore()
    await add_segments(app_db, store, org, interview, "screen-1", [0, 1])
    worker, ffmpeg = assembler(app_db, store)
    await worker.assemble_interview(org, interview, NOW)
    first = await load(app_db, org, interview, "screen-1")
    assert first.status == "assembled" and first.duration_ms == 20_000

    # The desktop drains its queue at the next launch: segment 2 arrives late.
    data = payload("screen-1", 2)
    late_path = f"{org}/interviews/{interview}/screen/screen-1-000002.mp4"
    store.blobs[late_path] = data
    async with app_db.tenant(org) as session:
        late = segment(
            org,
            interview,
            seq=2,
            started_at=T0 + timedelta(seconds=20),
            bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            blob_path=late_path,
        )
        session.add(late)
    await segment_service.acknowledge(
        app_db, store, org, interview, late.id, hashlib.sha256(data).hexdigest(), now=NOW
    )
    reopened = await load(app_db, org, interview, "screen-1")
    assert (reopened.status, reopened.attempts) == ("assembly-pending", 0)

    assert await worker.assemble_interview(org, interview, NOW) == 1
    again = await load(app_db, org, interview, "screen-1")
    assert again.status == "assembled" and again.duration_ms == 30_000
    assert len(ffmpeg.calls) == 2


async def test_the_sweep_picks_up_ended_interviews_across_organisations_and_ignores_the_rest(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    acme, globex = await make_organization("Acme"), await make_organization("Globex")
    store = FakeStore()
    ended = {}
    for org in (acme, globex):
        interview = await completed_interview(admin_engine, org, make_hiring, status="abandoned")
        await add_segments(
            app_db, store, org, interview, "mic", [0], container="webm", codec="opus"
        )
        ended[org] = interview
    live = await completed_interview(admin_engine, acme, make_hiring, status="in_progress")
    await add_segments(app_db, store, acme, live, "mic", [0], container="webm", codec="opus")
    worker, _ = assembler(app_db, store)
    await worker.run_due(NOW)
    for org, interview in ended.items():
        assert (await load(app_db, org, interview, "mic")).status == "assembled"
    assert (await load(app_db, acme, live, "mic")).status == "recording"


async def test_the_consumer_handler_assembles_the_interview_named_in_the_event(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    org = await make_organization("Acme")
    interview = await completed_interview(admin_engine, org, make_hiring)
    store = FakeStore()
    await add_segments(app_db, store, org, interview, "camera", [0], container="webm", codec="vp8")
    worker, _ = assembler(app_db, store)
    await handle_interview_ended(
        worker, org, {"interview_id": str(interview), "status": "completed"}
    )
    assert (await load(app_db, org, interview, "camera")).status == "assembled"
