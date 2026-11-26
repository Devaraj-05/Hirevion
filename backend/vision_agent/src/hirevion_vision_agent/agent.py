"""The third eye's vision agent (C7-1, ADR-0043): a LiveKit Agents worker the API dispatches to an
interview that uses a phone camera. It joins the room as an agent marked `hv.role=vision` (so its
leaving never summons another interviewer), subscribes to the phone's camera only, and hands its
frames to `ThirdEyeWatcher`, which records a second person or a phone as proctoring events with a
snapshot. One per interview (`hv:iv:{id}:vision`); it stops when the interview ends.

Run it locally beside the interview agent: `uv run python -m hirevion_vision_agent.agent dev`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from livekit import rtc
from livekit.agents import AgentServer, AutoSubscribe, JobContext, JobProcess, JobRequest, cli
from redis.asyncio import Redis

from hirevion_core.db.session import Database, create_database
from hirevion_core.interview_session.agent_load import session_load
from hirevion_core.interview_session.conductor import vision_key
from hirevion_core.interview_session.held_key import HeldKey
from hirevion_core.interview_session.media import (
    ROLE_ATTRIBUTE,
    THIRD_EYE_PREFIX,
    VISION_IDENTITY_PREFIX,
    VISION_ROLE,
)
from hirevion_core.models import Interview
from hirevion_core.proctoring.service import ProctorEngine
from hirevion_core.settings import load_core_settings
from hirevion_core.storage.service import StorageService, load_storage_settings
from hirevion_vision_agent.detector import Detector, MediaPipeDetector, rgb_from_frame
from hirevion_vision_agent.pose import MediaPipePose, PoseEstimator
from hirevion_vision_agent.settings import load_settings
from hirevion_vision_agent.watcher import ThirdEyeWatcher

log = logging.getLogger("hirevion.vision_agent")

# How often the agent checks whether the interview is still running.
POLL_SECONDS = 10.0
RUNNING = ("in_progress", "interrupted")


def job_ids(metadata: str) -> tuple[UUID, UUID]:
    """The interview and organisation the dispatch names (set by the API, never the client)."""
    data = json.loads(metadata or "{}")
    return UUID(str(data["interview_id"])), UUID(str(data["organization_id"]))


def is_phone_camera(publication: Any, participant: Any) -> bool:
    """The third eye's camera: the only track this agent looks at."""
    return (
        str(participant.identity).startswith(THIRD_EYE_PREFIX)
        and publication.kind == rtc.TrackKind.KIND_VIDEO
        and publication.source == rtc.TrackSource.SOURCE_CAMERA
    )


def still_running(status: str | None) -> bool:
    return status in RUNNING


async def interview_status(db: Database, organization_id: UUID, interview_id: UUID) -> str | None:
    async with db.tenant(organization_id) as session:
        interview = await session.get(Interview, interview_id)
        return interview.status if interview is not None else None


async def frames(track: rtc.Track) -> AsyncIterator[rtc.VideoFrame]:
    """The newest frame each time it is asked for one (older ones are dropped); the watcher
    converts only those it looks at."""
    stream = rtc.VideoStream(track, capacity=1, format=rtc.VideoBufferType.RGBA)
    try:
        async for event in stream:
            yield event.frame
    finally:
        await stream.aclose()


async def accept(request: JobRequest) -> None:
    """Joins as `vision-agent-…`, marked `hv.role=vision` in its token: from its first moment
    nothing takes it for the interviewer (whose leaving sends another)."""
    await request.accept(
        name="Vision",
        identity=f"{VISION_IDENTITY_PREFIX}{request.job.id}",
        attributes={ROLE_ATTRIBUTE: VISION_ROLE},
    )


async def stop(task: asyncio.Task[None] | None) -> None:
    """Cancels a watch and waits for it, so its open episodes are closed before the agent's
    connections are."""
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


def prewarm(process: JobProcess) -> None:
    # The model loads once per worker process, not per interview.
    process.userdata["detector"] = MediaPipeDetector()
    process.userdata["pose"] = MediaPipePose()


async def entrypoint(ctx: JobContext) -> None:
    interview_id, organization_id = job_ids(ctx.job.metadata)
    core = load_core_settings()
    db = create_database(core, "app")
    redis = Redis.from_url(core.valkey_url())
    storage = StorageService(load_storage_settings())
    lock = HeldKey(redis, vision_key(interview_id), owner=ctx.job.id)

    async def cleanup() -> None:
        await lock.release()
        await storage.aclose()
        await redis.aclose()
        await db.dispose()

    ctx.add_shutdown_callback(cleanup)
    if not await lock.acquire():
        ctx.shutdown(reason="another vision agent watches this interview")
        return
    detector: Detector = ctx.proc.userdata.get("detector") or MediaPipeDetector()
    pose: PoseEstimator = ctx.proc.userdata.get("pose") or MediaPipePose()
    watcher = ThirdEyeWatcher(
        organization_id, interview_id, detector, ProctorEngine(db, redis), storage, pose=pose
    )
    current: list[asyncio.Task[None]] = []

    await ctx.connect(auto_subscribe=AutoSubscribe.SUBSCRIBE_NONE)

    def subscribe(publication: rtc.RemoteTrackPublication, who: rtc.RemoteParticipant) -> None:
        if is_phone_camera(publication, who):
            publication.set_subscribed(True)

    def on_subscribed(
        track: rtc.Track, publication: rtc.RemoteTrackPublication, who: rtc.RemoteParticipant
    ) -> None:
        if not is_phone_camera(publication, who):
            return
        log.info("Watching the third eye of interview %s", interview_id)
        previous = current.pop() if current else None

        async def follow() -> None:
            # One watch at a time: a phone that republished replaces the old stream's watch.
            await stop(previous)
            await watcher.watch(frames(track), convert=rgb_from_frame)

        current.append(asyncio.create_task(follow()))

    ctx.room.on("track_published", subscribe)
    ctx.room.on("track_subscribed", on_subscribed)
    # A phone already in the room when the agent arrives.
    for participant in ctx.room.remote_participants.values():
        for publication in participant.track_publications.values():
            subscribe(publication, participant)

    while not lock.lost.is_set():
        await asyncio.sleep(POLL_SECONDS)
        try:
            if not still_running(await interview_status(db, organization_id, interview_id)):
                break
        except Exception:
            log.warning("Couldn't read interview %s's status; retrying", interview_id)
    await stop(current.pop() if current else None)
    ctx.shutdown(reason="interview over" if not lock.lost.is_set() else "lock lost")


def main() -> None:
    settings = load_settings()
    # Explicit dispatch only: the API sends this agent to an interview's room by name.
    os.environ.setdefault("LIVEKIT_AGENT_NAME", settings.hv_vision_agent_name)
    server = AgentServer(
        ws_url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret.get_secret_value(),
        setup_fnc=prewarm,
        load_fnc=session_load(settings.hv_vision_max_sessions),
        load_threshold=1.0,
    )
    server.rtc_session(entrypoint, on_request=accept)
    cli.run_app(server)


if __name__ == "__main__":
    main()
