"""Docker Compose command lines for the local stack."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

PROJECT_NAME = "hirevion"
COMPOSE_FILE = Path("infrastructure/local/compose.yaml")
DEFAULT_PROFILES: tuple[str, ...] = ("core", "edge", "media")
OPTIONAL_PROFILES: tuple[str, ...] = ("obs",)
ALL_PROFILES: tuple[str, ...] = (*DEFAULT_PROFILES, *OPTIONAL_PROFILES)


def select_profiles(include_obs: bool) -> list[str]:
    return [*DEFAULT_PROFILES, *(OPTIONAL_PROFILES if include_obs else ())]


def compose_command(repo_root: Path, profiles: Sequence[str], *args: str) -> list[str]:
    command = [
        "docker",
        "compose",
        "--project-name",
        PROJECT_NAME,
        "--env-file",
        str(repo_root / ".env"),
        "--file",
        str(repo_root / COMPOSE_FILE),
    ]
    for profile in profiles:
        command += ["--profile", profile]
    return [*command, *args]
