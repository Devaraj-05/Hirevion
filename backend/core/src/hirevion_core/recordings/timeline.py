"""The timeline map and the ffmpeg command line for assembling a track (SP-12), as pure functions.

An assembled file is its acknowledged segments back to back: gaps are not filled. The map says
where each segment sits in the file (`file_offset_ms`, the sum of the declared durations before
it) and when it started in server time, so a player turns file time into server time with
`started_at + (t - file_offset_ms)` inside a segment. Every segment re-anchors that clock to its
own start, so an error never grows beyond one segment's.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import groupby
from typing import Any

TIMELINE_VERSION = 1


@dataclass(frozen=True, slots=True)
class SegmentInfo:
    seq: int
    started_at: datetime
    duration_ms: int

    @property
    def ended_at(self) -> datetime:
        return self.started_at + timedelta(milliseconds=self.duration_ms)


@dataclass(frozen=True, slots=True)
class Gap:
    """Segment numbers `from_seq..to_seq` (inclusive) that are not in the file; the times are
    where the segment before ended and the one after started (None at the start of a track)."""

    from_seq: int
    to_seq: int
    from_time: datetime | None
    to_time: datetime | None
    reason: str  # "missing" or "corrupt" (it no longer matched its acknowledged hash)


def _ordered(segments: Sequence[SegmentInfo]) -> list[SegmentInfo]:
    ordered = sorted(segments, key=lambda s: s.seq)
    if len({s.seq for s in ordered}) != len(ordered):
        raise ValueError("a segment number appears twice")
    return ordered


def find_gaps(
    segments: Sequence[SegmentInfo], corrupt: Collection[int] = (), last_seq: int | None = None
) -> list[Gap]:
    """Every run of segment numbers the file doesn't hold, up to the track's last number: the
    highest of `last_seq` (what the desktop asked to upload), the corrupt ones and the included
    ones. Numbers skipped by the desktop and numbers never acknowledged are both `missing`; a gap
    after the last included segment has no `to_time`."""
    gaps: list[Gap] = []
    expected = 0
    previous_end: datetime | None = None

    def add(stop: int, to_time: datetime | None) -> None:
        for reason, run in groupby(
            range(expected, stop), key=lambda n: "corrupt" if n in corrupt else "missing"
        ):
            numbers = list(run)
            gaps.append(Gap(numbers[0], numbers[-1], previous_end, to_time, reason))

    for segment in _ordered(segments):
        if segment.seq > expected:
            add(segment.seq, segment.started_at)
        previous_end = segment.ended_at
        expected = segment.seq + 1
    end = max([expected - 1, *corrupt, *([] if last_seq is None else [last_seq])])
    if end >= expected:
        add(end + 1, None)
    return gaps


def build_timeline(
    track: str,
    container: str,
    segments: Sequence[SegmentInfo],
    corrupt: Collection[int] = (),
    last_seq: int | None = None,
) -> dict[str, Any]:
    """The JSON stored beside the assembled file."""
    ordered = _ordered(segments)
    if not ordered:
        raise ValueError("a track with no segments has no timeline")
    entries: list[dict[str, Any]] = []
    offset = 0
    for segment in ordered:
        entries.append(
            {
                "seq": segment.seq,
                "started_at": segment.started_at.isoformat(),
                "duration_ms": segment.duration_ms,
                "file_offset_ms": offset,
            }
        )
        offset += segment.duration_ms
    return {
        "version": TIMELINE_VERSION,
        "track": track,
        "container": container,
        "started_at": ordered[0].started_at.isoformat(),
        "ended_at": ordered[-1].ended_at.isoformat(),
        "duration_ms": offset,
        "segments": entries,
        "gaps": [
            {
                "from_seq": gap.from_seq,
                "to_seq": gap.to_seq,
                "from_time": gap.from_time.isoformat() if gap.from_time else None,
                "to_time": gap.to_time.isoformat() if gap.to_time else None,
                "reason": gap.reason,
            }
            for gap in find_gaps(ordered, corrupt, last_seq)
        ],
    }


def to_server_time(timeline: Mapping[str, Any], offset_ms: int) -> datetime:
    """The server time of `offset_ms` into the assembled file."""
    if offset_ms < 0:
        raise ValueError("the offset is before the start of the file")
    owner: Mapping[str, Any] | None = None
    for entry in timeline["segments"]:
        if entry["file_offset_ms"] <= offset_ms:
            owner = entry
    if owner is None:
        raise ValueError("the timeline has no segments")
    started = datetime.fromisoformat(owner["started_at"])
    return started + timedelta(milliseconds=offset_ms - owner["file_offset_ms"])


def concat_list(names: Sequence[str]) -> str:
    """The concat demuxer's list file: one quoted name per line."""
    lines = []
    for name in names:
        if "\n" in name or "\r" in name:
            raise ValueError("a segment name can't hold a newline")
        lines.append("file '" + name.replace("'", "'\\''") + "'")
    return "\n".join(lines) + "\n"


def concat_command(ffmpeg: str, list_file: str, output: str, container: str) -> list[str]:
    """ffmpeg joining the listed files without re-encoding. Names are relative to the working
    directory the caller runs it in (the demuxer's default `-safe 1` allows nothing else)."""
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-f",
        "concat",
        "-i",
        list_file,
        "-c",
        "copy",
    ]
    if container == "mp4":
        command += ["-movflags", "+faststart"]
    return [*command, output]
