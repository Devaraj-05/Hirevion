"""The vision agent's frame loop (C7-1): samples the phone's picture, runs the detector in a
thread, and turns episodes into proctoring events with a snapshot of the frame that started them.

At most `INTERVAL_SECONDS` apart, and one detection at a time: a slow frame makes the next ones
skip, never queue. Frames are analysed in memory; only an episode's snapshot is stored, under the
interview's evidence, before the event that links it is recorded.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from hirevion_core.proctoring.service import Snapshot
from hirevion_core.storage.paths import BlobPath, interview_blob
from hirevion_vision_agent.detector import Detector, Pixels, jpeg
from hirevion_vision_agent.watch import (
    EVENTS,
    PERSON_MIN_AREA,
    PERSON_MIN_SCORE,
    PHONE_MIN_SCORE,
    Detection,
    Ended,
    Kind,
    Started,
    Watch,
    seen,
)

log = logging.getLogger(__name__)

INTERVAL_SECONDS = 0.5


class Recorder(Protocol):
    """What `ProctorEngine` offers the agent."""

    async def detected(
        self,
        organization_id: UUID,
        interview_id: UUID,
        *,
        event: str,
        started_at: datetime,
        duration_ms: int,
        details: dict[str, Any],
        snapshot: Snapshot | None,
    ) -> UUID | None: ...

    async def detection_ended(
        self, organization_id: UUID, interview_id: UUID, event_id: UUID, *, duration_ms: int
    ) -> None: ...


class Uploads(Protocol):
    async def put(self, path: BlobPath, data: bytes, content_type: str) -> None: ...


def summary(found: list[Detection], width: int, height: int) -> dict[str, Any]:
    """What the event records about the frame: counts and the best scores, no pixels."""
    least = PERSON_MIN_AREA * width * height
    people = [
        d.score
        for d in found
        if d.label == "person" and d.score >= PERSON_MIN_SCORE and d.width * d.height >= least
    ]
    phones = [d.score for d in found if d.label == "cell phone" and d.score >= PHONE_MIN_SCORE]
    details: dict[str, Any] = {"people": len(people), "phones": len(phones)}
    if people:
        details["best_person"] = round(max(people), 2)
    if phones:
        details["best_phone"] = round(max(phones), 2)
    return details


class ThirdEyeWatcher:
    def __init__(
        self,
        organization_id: UUID,
        interview_id: UUID,
        detector: Detector,
        recorder: Recorder,
        uploads: Uploads,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        interval: float = INTERVAL_SECONDS,
    ) -> None:
        self._org = organization_id
        self._interview = interview_id
        self._detector = detector
        self._recorder = recorder
        self._uploads = uploads
        self._now = now
        self._interval = interval
        self._watch = Watch()
        self._open: dict[Kind, UUID] = {}

    async def watch(self, frames: AsyncIterator[Pixels]) -> None:
        """Checks the frames, at most one every `interval` seconds."""
        last: datetime | None = None
        async for pixels in frames:
            now = self._now()
            if last is not None and (now - last).total_seconds() < self._interval:
                continue
            last = now
            try:
                await self.frame(pixels)
            except Exception:
                # One bad frame (a storage hiccup, a detector error) mustn't stop the watch.
                log.exception("The third eye's frame couldn't be checked")

    async def frame(self, pixels: Pixels) -> None:
        now = self._now()
        found = await asyncio.to_thread(self._detector.detect, pixels)
        height, width = pixels.shape[0], pixels.shape[1]
        for change in self._watch.update(now.timestamp(), seen(found, width, height)):
            if isinstance(change, Started):
                await self._started(change, now, pixels, summary(found, width, height))
            else:
                await self._ended(change)

    async def _started(
        self, change: Started, now: datetime, pixels: Pixels, details: dict[str, Any]
    ) -> None:
        started_at = datetime.fromtimestamp(change.at, UTC)
        data = jpeg(pixels)
        name = f"third-eye-{change.kind}-{int(now.timestamp() * 1000)}.jpg"
        path = interview_blob(self._org, self._interview, "evidence", name)
        await self._uploads.put(path, data, "image/jpeg")
        event_id = await self._recorder.detected(
            self._org,
            self._interview,
            event=EVENTS[change.kind],
            started_at=started_at,
            duration_ms=int((now - started_at).total_seconds() * 1000),
            details=details,
            snapshot=Snapshot(str(path), len(data), hashlib.sha256(data).hexdigest()),
        )
        if event_id is not None:
            self._open[change.kind] = event_id

    async def _ended(self, change: Ended) -> None:
        event_id = self._open.pop(change.kind, None)
        if event_id is None:
            return
        await self._recorder.detection_ended(
            self._org,
            self._interview,
            event_id,
            duration_ms=int((change.at - change.started_at) * 1000),
        )
