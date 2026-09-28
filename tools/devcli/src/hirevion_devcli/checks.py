"""Environment checks used by `hv doctor`."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from .envfile import missing_required

Status = Literal["ok", "warn", "fail"]
Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
Which = Callable[[str], str | None]

MIN_DOCKER_MEMORY_BYTES = 8 * 1024**3
MIN_DOCKER_CPUS = 4
_VERSION = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: Status
    detail: str


def run_command(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    # Fixed tool names and arguments only; never a shell, never user input.
    return subprocess.run(list(args), capture_output=True, text=True, timeout=60, check=False)  # noqa: S603


def find_tool(name: str) -> str | None:
    """Find a tool on PATH; `uv run` exposes its own binary as $UV."""
    found = shutil.which(name)
    if found is None and name == "uv":
        return os.environ.get("UV")
    return found


def parse_version(text: str) -> tuple[int, int, int] | None:
    match = _VERSION.search(text)
    if match is None:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch or 0)


def _dotted(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)


def check_tool(
    name: str,
    version_args: Sequence[str],
    minimum: tuple[int, int, int],
    *,
    required: bool = True,
    which: Which = find_tool,
    runner: Runner = run_command,
) -> CheckResult:
    missing: Status = "fail" if required else "warn"
    path = which(name)
    if path is None:
        return CheckResult(name, missing, "not found on PATH")
    completed = runner([path, *version_args])
    version = parse_version(completed.stdout + completed.stderr)
    if version is None:
        return CheckResult(name, "warn", "found, but its version could not be read")
    if version < minimum:
        return CheckResult(name, missing, f"{_dotted(version)} found; {_dotted(minimum)}+ needed")
    return CheckResult(name, "ok", _dotted(version))


def check_docker(*, which: Which = find_tool, runner: Runner = run_command) -> CheckResult:
    path = which("docker")
    if path is None:
        return CheckResult("docker", "fail", "Docker Desktop not found on PATH")
    completed = runner([path, "info", "--format", "{{json .}}"])
    if completed.returncode != 0:
        return CheckResult("docker", "fail", "Docker Desktop is not running")
    info = json.loads(completed.stdout)
    memory = int(info.get("MemTotal", 0))
    cpus = int(info.get("NCPU", 0))
    detail = f"{memory / 1024**3:.1f} GB RAM, {cpus} CPUs available to Docker"
    if memory < MIN_DOCKER_MEMORY_BYTES or cpus < MIN_DOCKER_CPUS:
        return CheckResult("docker", "warn", f"{detail} (8 GB and 4 CPUs recommended)")
    return CheckResult("docker", "ok", detail)


def check_env(values: dict[str, str] | None) -> CheckResult:
    if values is None:
        return CheckResult(".env", "fail", "missing; run `uv run hv init-env`")
    missing = missing_required(values)
    if missing:
        return CheckResult(".env", "fail", "add " + ", ".join(missing))
    return CheckResult(".env", "ok", "API keys present")
