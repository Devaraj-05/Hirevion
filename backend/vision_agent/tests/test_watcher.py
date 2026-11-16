"""The vision agent's frame loop (C7-1), with a fake detector, recorder and storage: what it
uploads and records when the phone's picture shows a phone, and how often it looks."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import numpy as np

from hirevion_core.proctoring.service import Snapshot
from hirevion_core.storage.paths import BlobPath
from hirevion_vision_agent.watch import Detection
from hirevion_vision_agent.watcher import ThirdEyeWatcher

ORG, INTERVIEW = UUID(int=1), UUID(int=2)
T0 = datetime(2026, 11, 16, 13, 0, tzinfo=UTC)
PHONE = Detection("cell phone", 0.71, 30, 40, 6, 11)
FRAME = np.zeros((72, 128, 3), dtype=np.uint8)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


class Detector:
    def __init__(self, script: list[list[Detection]]) -> None:
        self.script = script
        self.calls = 0

    def detect(self, pixels: Any) -> list[Detection]:
        found = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return found

    def close(self) -> None:
        return None


class Recorder:
    def __init__(self, answer: UUID | None = None) -> None:
        self.answer = answer if answer is not None else uuid4()
        self.detected_calls: list[dict[str, Any]] = []
        self.ended_calls: list[tuple[UUID, int]] = []

    async def detected(
        self, organization_id: UUID, interview_id: UUID, **fields: Any
    ) -> UUID | None:
        self.detected_calls.append({"org": organization_id, "interview": interview_id, **fields})
        return self.answer

    async def detection_ended(
        self, organization_id: UUID, interview_id: UUID, event_id: UUID, *, duration_ms: int
    ) -> None:
        self.ended_calls.append((event_id, duration_ms))


class Uploads:
    def __init__(self) -> None:
        self.put_calls: list[tuple[str, bytes, str]] = []

    async def put(self, path: BlobPath, data: bytes, content_type: str) -> None:
        self.put_calls.append((str(path), data, content_type))

    async def delete(self, path: BlobPath) -> None:
        return None


def watcher(script: list[list[Detection]], recorder: Recorder | None = None):
    clock = Clock()
    parts = (Detector(script), recorder or Recorder(), Uploads())
    return ThirdEyeWatcher(ORG, INTERVIEW, *parts, now=clock), clock, parts


async def frames_every(clock: Clock, seconds: float, count: int) -> AsyncIterator[Any]:
    for _ in range(count):
        yield FRAME
        clock.now += timedelta(seconds=seconds)


async def test_a_phone_held_2_s_is_recorded_once_with_its_snapshot() -> None:
    watch, clock, (_, recorder, uploads) = watcher([[PHONE]])
    for _ in range(6):  # 0, 0.5, ... 2.5 s
        await watch.frame(FRAME)
        clock.now += timedelta(seconds=0.5)
    ((path, data, kind),) = uploads.put_calls
    assert path.startswith(f"{ORG}/interviews/{INTERVIEW}/evidence/third-eye-phone-")
    assert path.endswith(".jpg") and data[:2] == b"\xff\xd8" and kind == "image/jpeg"
    (call,) = recorder.detected_calls
    assert call["event"] == "PHONE_DETECTED" and call["started_at"] == T0
    assert call["duration_ms"] == 2_000
    assert call["details"] == {"people": 0, "phones": 1, "best_phone": 0.71}
    assert call["snapshot"] == Snapshot(path, len(data), hashlib.sha256(data).hexdigest())


async def test_the_episode_ends_with_its_length_once_the_phone_is_gone() -> None:
    event_id = uuid4()
    watch, clock, (_, recorder, _) = watcher([[PHONE]] * 6 + [[]] * 20, Recorder(event_id))
    for _ in range(18):  # the phone for 3 s, then 6 s without it
        await watch.frame(FRAME)
        clock.now += timedelta(seconds=0.5)
    assert recorder.ended_calls == [(event_id, 2_500)]


async def test_nothing_more_happens_when_proctoring_isnt_recording() -> None:
    watch, clock, (_, recorder, _) = watcher([[PHONE]] * 6 + [[]] * 20, Recorder())
    recorder.answer = None  # type: ignore[assignment]  # proctoring off: no event id
    for _ in range(18):
        await watch.frame(FRAME)
        clock.now += timedelta(seconds=0.5)
    assert len(recorder.detected_calls) == 1 and recorder.ended_calls == []


async def test_it_looks_at_most_twice_a_second() -> None:
    watch, clock, (detector, _, _) = watcher([[]])
    await watch.watch(frames_every(clock, 0.1, 30))  # 30 frames over 3 s
    assert 5 <= detector.calls <= 7


class DeletingUploads(Uploads):
    def __init__(self) -> None:
        super().__init__()
        self.deleted: list[str] = []

    async def delete(self, path: BlobPath) -> None:
        self.deleted.append(str(path))


async def test_a_snapshot_nothing_recorded_is_deleted_again() -> None:
    """Proctoring off or paused: no event links the frame, so it mustn't stay in storage."""
    clock = Clock()
    recorder, uploads = Recorder(), DeletingUploads()
    recorder.answer = None  # type: ignore[assignment]
    watch = ThirdEyeWatcher(ORG, INTERVIEW, Detector([[PHONE]]), recorder, uploads, now=clock)
    for _ in range(6):
        await watch.frame(FRAME)
        clock.now += timedelta(seconds=0.5)
    ((path, _, _),) = uploads.put_calls
    assert uploads.deleted == [path]


async def test_an_open_episode_is_closed_when_the_phones_stream_ends() -> None:
    event_id = uuid4()
    watch, clock, (_, recorder, _) = watcher([[PHONE]], Recorder(event_id))
    await watch.watch(frames_every(clock, 0.5, 6))  # 3 s of a phone, then the stream ends
    assert recorder.ended_calls == [(event_id, 2_500)]


async def test_only_the_frames_it_looks_at_are_converted() -> None:
    watch, clock, _ = watcher([[]])
    converted: list[Any] = []

    def convert(raw: Any) -> Any:
        converted.append(raw)
        return FRAME

    await watch.watch(frames_every(clock, 0.1, 30), convert=convert)
    assert 5 <= len(converted) <= 7
