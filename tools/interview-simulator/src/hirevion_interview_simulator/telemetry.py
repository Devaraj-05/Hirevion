"""What the desktop sends while an interview runs, besides the answers (SP-17): a proctor session
with events that fall in every section of PRD §68's report, a heartbeat, and short recording
segments for the camera, microphone and screen. A run through the simulator then has data for the
proctoring report and the review workspace, as a real one would.

The events are scripted, not random: the same run always makes the same report."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from hirevion_interview_simulator.client import DesktopClient

# (event, source, duration_ms, confidence, details): one for each of the report's event sections.
SCRIPT: tuple[tuple[str, str, int | None, float, dict[str, Any]], ...] = (
    (
        "APPLICATION_FOCUS_CHANGE",
        "native",
        4_000,
        1.0,
        {"previous_app": "interview", "new_app": "chrome"},
    ),
    (
        "BLOCKED_PROCESS_DETECTED",
        "native",
        None,
        1.0,
        {"category": "remote_access", "process": "anydesk"},
    ),
    ("FACE_ABSENT", "camera", 7_000, 0.92, {"phase": "ended", "level": "warning"}),
    ("GAZE_DEVIATION", "camera", 12_000, 0.7, {}),
    ("PHONE_DETECTED", "camera", 2_000, 0.88, {}),
    ("EXTERNAL_DISPLAY_CHANGE", "native", None, 1.0, {"displays": 2}),
    ("CAMERA_DISCONNECTED", "camera", 3_000, 1.0, {}),
    ("CAMERA_RECONNECTED", "camera", None, 1.0, {}),
)
TRACKS = (
    ("camera", "webm", "vp8"),
    ("mic", "webm", "opus"),
    ("screen-1", "mp4", "h264"),
)
SEGMENTS_PER_TRACK = 2
SEGMENT_MS = 10_000


@dataclass
class TelemetryReport:
    proctor_session_id: str
    events: int
    segments: int
    refused: list[str] = field(default_factory=list)


def segment_bytes(track: str, seq: int) -> bytes:
    """Stand-in media: enough to be stored, hashed and acknowledged (it isn't playable)."""
    return f"simulated {track} segment {seq}\n".encode() * 64


async def send_telemetry(
    client: DesktopClient,
    interview_id: str,
    *,
    uploader: httpx.AsyncClient,
    storage_urls: tuple[str, str] | None = None,
) -> TelemetryReport:
    """Opens the interview's proctor session, sends its events and a heartbeat, and uploads and
    acknowledges the recording segments. `storage_urls` is (public, internal): the desktop
    uploads to the public address, which a script on this machine reaches by the internal one."""
    opened = await client.open_proctor_session(interview_id)
    session_id = str(opened["proctor_session_id"])
    now = datetime.now(UTC)
    events = [
        {
            "seq": number,
            "event": name,
            "source": source,
            "started_at": (now - timedelta(milliseconds=(len(SCRIPT) - number) * 100)).isoformat(),
            **({"duration_ms": duration} if duration is not None else {}),
            "confidence": confidence,
            "details": details,
        }
        for number, (name, source, duration, confidence, details) in enumerate(SCRIPT, start=1)
    ]
    await client.proctor_events(interview_id, session_id, events)
    await client.proctor_heartbeat(interview_id, session_id, seq_high=len(events))
    report = TelemetryReport(session_id, len(events), 0)
    started = now - timedelta(seconds=SEGMENT_MS * SEGMENTS_PER_TRACK / 1000)
    for track, container, codec in TRACKS:
        for seq in range(SEGMENTS_PER_TRACK):
            data = segment_bytes(track, seq)
            digest = hashlib.sha256(data).hexdigest()
            asked = await client.ask_segment_upload(
                interview_id,
                {
                    "interview_id": interview_id,
                    "track": track,
                    "seq": seq,
                    "started_at": (started + timedelta(milliseconds=seq * SEGMENT_MS)).isoformat(),
                    "duration_ms": SEGMENT_MS,
                    "bytes": len(data),
                    "sha256": digest,
                    "container": container,
                    "codec": codec,
                },
            )
            url = str(asked["upload_url"])
            if storage_urls is not None:
                url = url.replace(*storage_urls, 1)
            put = await uploader.put(url, content=data, headers=asked["headers"])
            if put.status_code >= 300:
                report.refused.append(f"{track}-{seq}: {put.status_code}")
                continue
            await client.acknowledge_segment(interview_id, str(asked["segment_id"]), digest)
            report.segments += 1
    return report
