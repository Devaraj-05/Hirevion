"""The real ffmpeg joining real segments without re-encoding (SP-12). Skipped where ffmpeg isn't
installed (`HV_FFMPEG_PATH` or PATH); the fake in `test_recording_assembly.py` covers the logic."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from hirevion_core.recordings.ffmpeg import Ffmpeg, FfmpegError, FfmpegMissing

FFMPEG = shutil.which(os.environ.get("HV_FFMPEG_PATH", "ffmpeg"))
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg isn't installed")


def run(*arguments: str) -> str:
    assert FFMPEG is not None
    done = subprocess.run(  # noqa: S603 (our own arguments, no shell)
        [FFMPEG, "-hide_banner", *arguments], capture_output=True, text=True, check=False
    )
    return done.stderr


def make_segment(path: Path, *, hertz: int) -> None:
    """A 2-second MP4 with H.264 video and AAC audio, the codecs a screen segment carries."""
    error = run(
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=2:size=320x240:rate=25",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={hertz}:duration=2",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(path),
    )
    assert path.exists(), error


def duration_seconds(path: Path) -> float:
    found = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", run("-i", str(path)))
    assert found is not None
    hours, minutes, seconds = found.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


@needs_ffmpeg
async def test_segments_are_joined_into_one_playable_file(tmp_path: Path) -> None:
    names = ["seg-000000.mp4", "seg-000001.mp4", "seg-000002.mp4"]
    for index, name in enumerate(names):
        make_segment(tmp_path / name, hertz=440 + index * 100)
    await Ffmpeg(FFMPEG or "ffmpeg").concat(tmp_path, names, "assembled.mp4", "mp4")
    produced = tmp_path / "assembled.mp4"
    assert produced.exists()
    assert 5.6 < duration_seconds(produced) < 6.5  # three 2-second segments, back to back
    assert "Error" not in run("-v", "error", "-i", str(produced), "-f", "null", "-")


@needs_ffmpeg
async def test_a_file_ffmpeg_cannot_read_is_an_error_not_a_crash(tmp_path: Path) -> None:
    (tmp_path / "seg-000000.mp4").write_bytes(b"this is not a video")
    with pytest.raises(FfmpegError, match="exited with"):
        await Ffmpeg(FFMPEG or "ffmpeg").concat(
            tmp_path, ["seg-000000.mp4"], "assembled.mp4", "mp4"
        )


async def test_a_missing_binary_is_reported_not_raised_as_an_os_error(tmp_path: Path) -> None:
    missing = Ffmpeg("hirevion-no-such-ffmpeg")
    assert not missing.available()
    with pytest.raises(FfmpegMissing, match="isn't installed"):
        await missing.concat(tmp_path, ["a.mp4"], "out.mp4", "mp4")
