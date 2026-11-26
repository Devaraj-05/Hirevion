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
from hirevion_vision_agent.pose import PoseEstimator
from hirevion_vision_agent.scene import Scene
from hirevion_vision_agent.watch import (
    EVENTS,
    Detection,
    Ended,
    Kind,
    Started,
    Watch,
    people_and_phones,
    screens,
    seen,
)

log = logging.getLogger(__name__)

INTERVAL_SECONDS = 0.5
# The pose model is the heavier one: it runs at most once a second, and only with someone there.
POSE_EVERY_SECONDS = 1.0
# An open episode tells the server how long it has lasted this often, so one that keeps going
# (the candidate away for minutes) becomes critical while it happens, not only once it is over.
PROGRESS_SECONDS = 10.0


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

    async def detection_progress(
        self, organization_id: UUID, interview_id: UUID, event_id: UUID, *, duration_ms: int
    ) -> None: ...


class Uploads(Protocol):
    async def put(self, path: BlobPath, data: bytes, content_type: str) -> None: ...

    async def delete(self, path: BlobPath) -> None: ...


def summary(found: list[Detection], width: int, height: int) -> dict[str, Any]:
    """What the event records about the frame: counts and the best scores, no pixels. Counted by
    the same rule that decides the episode (`people_and_phones`)."""
    people, phones = people_and_phones(found, width, height)
    details: dict[str, Any] = {"people": len(people), "phones": len(phones)}
    if people:
        details["best_person"] = round(max(d.score for d in people), 2)
    if phones:
        details["best_phone"] = round(max(d.score for d in phones), 2)
    shown = screens(found, width, height)
    if shown:
        details["screens"] = len(shown)
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
        pose: PoseEstimator | None = None,
    ) -> None:
        self._org = organization_id
        self._interview = interview_id
        self._detector = detector
        self._recorder = recorder
        self._uploads = uploads
        self._now = now
        self._interval = interval
        self._watch = Watch()
        self._scene = Scene()
        self._pose = pose
        self._posed_at: datetime | None = None
        self._hands: bool | None = None
        self._open: dict[Kind, UUID] = {}
        # Each open episode's start and when the server last heard how long it has lasted.
        self._since: dict[Kind, datetime] = {}
        self._told: dict[Kind, datetime] = {}

    async def watch(
        self, frames: AsyncIterator[Any], convert: Callable[[Any], Pixels] = lambda raw: raw
    ) -> None:
        """Checks the frames, at most one every `interval` seconds; only those are converted to
        pixels. When the frames stop (the phone left, the watch is cancelled), the open
        episodes are closed."""
        last: datetime | None = None
        try:
            async for raw in frames:
                now = self._now()
                if last is not None and (now - last).total_seconds() < self._interval:
                    continue
                last = now
                try:
                    await self.frame(convert(raw))
                except Exception:
                    # One bad frame (a storage hiccup, a detector error) mustn't stop the watch.
                    log.exception("The third eye's frame couldn't be checked")
        finally:
            await self.close()

    async def close(self) -> None:
        """Ends the open episodes where they were last seen."""
        for ended in self._watch.close_all():
            try:
                await self._ended(ended)
            except Exception:
                log.exception("The third eye's %s episode couldn't be closed", ended.kind)

    async def frame(self, pixels: Pixels) -> None:
        now = self._now()
        found = await asyncio.to_thread(self._detector.detect, pixels)
        height, width = pixels.shape[0], pixels.shape[1]
        flags: dict[Kind, bool] = dict(seen(found, width, height))
        # The scene and the pose are extra looks: one that fails mustn't cost the person and
        # phone checks their frame (review, 2026-11-26).
        try:
            flags.update(self._scene.update(now.timestamp(), pixels))
            readable = self._scene.readable
        except Exception:
            log.exception("The third eye's scene couldn't be measured")
            readable = True
        if not readable:
            # A covered or dark picture says nothing about where the candidate is.
            del flags["left_view"]
        people, _ = people_and_phones(found, width, height)
        try:
            hands = await self._hands_visible(now, pixels, present=bool(people))
        except Exception:
            log.exception("The third eye's pose couldn't be read")
            hands = None
        flags["hands_out_of_view"] = hands is False
        for change in self._watch.update(now.timestamp(), flags):
            if isinstance(change, Started):
                details = {**summary(found, width, height), **self._measures(change.kind, hands)}
                await self._started(change, now, pixels, details)
            else:
                await self._ended(change)
        await self._progress(now)

    async def _progress(self, now: datetime) -> None:
        """Each open episode's length so far: up to its latest sighting, not to now (an episode
        stays open a few seconds after the last one, and those mustn't count)."""
        for kind, event_id in list(self._open.items()):
            told = self._told.get(kind)
            if told is not None and (now - told).total_seconds() < PROGRESS_SECONDS:
                continue
            self._told[kind] = now
            last = self._watch.last_seen(kind)
            until = datetime.fromtimestamp(last, UTC) if last is not None else now
            lasted = max(0, int((until - self._since[kind]).total_seconds() * 1000))
            await self._recorder.detection_progress(
                self._org, self._interview, event_id, duration_ms=lasted
            )

    async def _hands_visible(self, now: datetime, pixels: Pixels, *, present: bool) -> bool | None:
        """The pose's answer, refreshed at most once a second; None with nobody there."""
        if self._pose is None or not present:
            self._hands, self._posed_at = None, None
            return None
        due = self._posed_at is None or (now - self._posed_at).total_seconds() >= POSE_EVERY_SECONDS
        if due:
            self._hands = await asyncio.to_thread(self._pose.hands_visible, pixels)
            self._posed_at = now
        return self._hands

    def _measures(self, kind: Kind, hands: bool | None) -> dict[str, Any]:
        """What backs the scene and pose signals: numbers only."""
        if kind == "hands_out_of_view":
            return {"hands_visible": hands}
        if kind == "unusual_movement":
            return {"motion": round(self._scene.motion, 3)}
        if kind == "view_changed" and self._scene.match is not None:
            return {"view_match": round(self._scene.match, 2)}
        return {}

    async def _started(
        self, change: Started, now: datetime, pixels: Pixels, details: dict[str, Any]
    ) -> None:
        started_at = datetime.fromtimestamp(change.at, UTC)
        log.info("Third eye of interview %s: %s seen", self._interview, EVENTS[change.kind])
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
        if event_id is None:
            # Nothing recorded it (proctoring off or paused): no event links the frame, so it
            # mustn't stay in storage.
            await self._uploads.delete(path)
            return
        self._open[change.kind] = event_id
        self._since[change.kind] = started_at
        self._told[change.kind] = now

    async def _ended(self, change: Ended) -> None:
        event_id = self._open.pop(change.kind, None)
        self._since.pop(change.kind, None)
        self._told.pop(change.kind, None)
        log.info("Third eye of interview %s: %s over", self._interview, EVENTS[change.kind])
        if event_id is None:
            return
        await self._recorder.detection_ended(
            self._org,
            self._interview,
            event_id,
            duration_ms=int((change.at - change.started_at) * 1000),
        )
