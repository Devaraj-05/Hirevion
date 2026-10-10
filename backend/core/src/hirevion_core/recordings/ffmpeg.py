"""ffmpeg as a separate process (SP-12). The media worker never links a media library: it writes a
list file, runs the binary with the concat demuxer and `-c copy`, and reads its exit code. No
shell is involved and every argument is ours."""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from hirevion_core.recordings.timeline import concat_command, concat_list


class FfmpegError(RuntimeError):
    """ffmpeg ran and failed, or timed out."""


class FfmpegMissing(FfmpegError):
    """There is no ffmpeg to run."""


class Concatenator(Protocol):
    def available(self) -> bool: ...

    async def concat(
        self, workdir: Path, names: Sequence[str], output: str, container: str
    ) -> None: ...


class Ffmpeg:
    def __init__(self, path: str = "ffmpeg", timeout: float = 900.0) -> None:
        self.path = path
        self.timeout = timeout

    def resolve(self) -> str | None:
        return shutil.which(self.path)

    def available(self) -> bool:
        return self.resolve() is not None

    async def concat(
        self, workdir: Path, names: Sequence[str], output: str, container: str
    ) -> None:
        """Joins `names` (files in `workdir`, in order) into `workdir/output` without
        re-encoding."""
        executable = self.resolve()
        if executable is None:
            raise FfmpegMissing(f"ffmpeg isn't installed ({self.path!r} isn't on PATH)")
        (workdir / "list.txt").write_bytes(concat_list(names).encode("utf-8"))
        command = concat_command(executable, "list.txt", output, container)
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=workdir,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(process.communicate(), self.timeout)
        except TimeoutError as error:
            process.kill()
            await process.wait()
            raise FfmpegError(f"ffmpeg took longer than {self.timeout:.0f}s") from error
        if process.returncode != 0:
            tail = stderr.decode("utf-8", "replace").strip()[-500:]
            raise FfmpegError(f"ffmpeg exited with {process.returncode}: {tail}")
