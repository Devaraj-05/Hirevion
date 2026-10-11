"""Tracks, their formats and their blob names (PRD §50, §85; `docs/api/contracts/recordings.md`).

The desktop records `screen-1`, `screen-2`, ... (one per display), `camera` and `mic`. A
segment's blob is `{org}/interviews/{id}/{screen|camera|audio}/{track}-{seq:06d}.{ext}`; the
assembled file and its timeline map sit in the same folder as `{track}-full.{ext}` and
`{track}-timeline.json`. Everything here is pure.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Literal

from hirevion_core.storage.paths import InterviewArtifact

TrackKind = Literal["screen", "camera", "mic"]
Container = Literal["mp4", "webm"]
Codec = Literal["h264", "vp8", "opus", "aac"]

TRACK_PATTERN = r"screen-[1-8]|camera|mic"
_TRACK = re.compile(TRACK_PATTERN)

# The contract's limits. 50 MB is 50,000,000 bytes (the desktop's reading of it).
MAX_SEGMENT_BYTES = 50_000_000
MAX_SEGMENT_MS = 60_000
# `seq` may skip numbers, so it is capped to keep a recovery listing small (about 28 hours).
MAX_SEQ = 10_000

_FORMATS: dict[TrackKind, frozenset[tuple[str, str]]] = {
    "screen": frozenset({("mp4", "h264")}),
    "camera": frozenset({("webm", "vp8"), ("webm", "opus"), ("mp4", "h264"), ("mp4", "aac")}),
    "mic": frozenset({("webm", "vp8"), ("webm", "opus"), ("mp4", "h264"), ("mp4", "aac")}),
}
_FOLDERS: dict[TrackKind, InterviewArtifact] = {
    "screen": "screen",
    "camera": "camera",
    "mic": "audio",
}
# The key of each kind in an interview's pinned `policy["recording"]`.
_POLICY_KEYS: dict[TrackKind, str] = {"screen": "screen", "camera": "camera", "mic": "audio"}


def is_track(track: str) -> bool:
    return _TRACK.fullmatch(track) is not None


def kind(track: str) -> TrackKind:
    if not is_track(track):
        raise ValueError(f"not a recording track: {track!r}")
    return "screen" if track.startswith("screen-") else track  # type: ignore[return-value]


def folder(track: str) -> InterviewArtifact:
    return _FOLDERS[kind(track)]


def track_order(track: str) -> tuple[int, int]:
    """Screens first (by display), then the camera, then the mic."""
    which = kind(track)
    if which == "screen":
        return (0, int(track.removeprefix("screen-")))
    return (1 if which == "camera" else 2, 0)


def format_allowed(track: str, container: str, codec: str) -> bool:
    return (container, codec) in _FORMATS[kind(track)]


def is_recorded(policy: Mapping[str, Any], track: str) -> bool:
    """Whether the interview's pinned policy records `track`; a missing key means recorded."""
    recording = policy.get("recording")
    if not isinstance(recording, Mapping):
        return True
    return bool(recording.get(_POLICY_KEYS[kind(track)], True))


def expected_tracks(policy: Mapping[str, Any]) -> list[str]:
    """The tracks every desktop must produce under `policy` (a second display is optional)."""
    return [t for t in ("screen-1", "camera", "mic") if is_recorded(policy, t)]


def segment_filename(track: str, seq: int, container: str) -> str:
    if not is_track(track) or seq < 0:
        raise ValueError("not a segment")
    return f"{track}-{seq:06d}.{container}"


def _build_suffix(build: str | None) -> str:
    """Each assembly writes its own files (`build` names it), so a stale build can never
    overwrite a newer one."""
    if build is None:
        return ""
    if not build.isalnum():
        raise ValueError("not a build name")
    return f"-{build}"


def assembled_filename(track: str, container: str, build: str | None = None) -> str:
    if not is_track(track):
        raise ValueError("not a recording track")
    return f"{track}-full{_build_suffix(build)}.{container}"


def timeline_filename(track: str, build: str | None = None) -> str:
    if not is_track(track):
        raise ValueError("not a recording track")
    return f"{track}-timeline{_build_suffix(build)}.json"


def content_type(track: str, container: str) -> str:
    base = "audio" if kind(track) == "mic" else "video"
    return f"{base}/{container}"
