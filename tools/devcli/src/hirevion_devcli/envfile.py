"""Read and create the gitignored root .env file used for local development."""

from __future__ import annotations

import re
import secrets
from pathlib import Path

REQUIRED_KEYS: tuple[str, ...] = ("OPENAI_API_KEY", "DEEPGRAM_API_KEY")
GENERATED_KEYS: dict[str, int] = {
    "POSTGRES_PASSWORD": 32,
    "LIVEKIT_API_SECRET": 48,
    "GLITCHTIP_SECRET_KEY": 50,
}
_PLACEHOLDER = re.compile(r"^(<.*>|changeme|replace[-_ ]?me|your[-_ ].*)$", re.IGNORECASE)


def parse_env(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines, ignoring blanks and comments; strips quotes and 'export '."""
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def is_placeholder(value: str) -> bool:
    stripped = value.strip()
    return not stripped or _PLACEHOLDER.match(stripped) is not None


def missing_required(
    values: dict[str, str], required: tuple[str, ...] = REQUIRED_KEYS
) -> list[str]:
    return [key for key in required if is_placeholder(values.get(key, ""))]


def generate_local_secrets() -> dict[str, str]:
    return {key: secrets.token_urlsafe(length)[:length] for key, length in GENERATED_KEYS.items()}


def render_env(example_text: str, generated: dict[str, str]) -> str:
    """Return the example text with empty generated-secret keys filled in."""
    lines: list[str] = []
    for line in example_text.splitlines():
        name, sep, value = line.partition("=")
        name = name.strip()
        is_comment = line.lstrip().startswith("#")
        if sep and not is_comment and name in generated and not value.strip():
            lines.append(f"{name}={generated[name]}")
        else:
            lines.append(line)
    return "\n".join(lines) + "\n"


def init_env(example_path: Path, env_path: Path) -> bool:
    """Create env_path from example_path with fresh local secrets; never overwrites."""
    if env_path.exists():
        return False
    example_text = example_path.read_text(encoding="utf-8")
    env_path.write_text(render_env(example_text, generate_local_secrets()), encoding="utf-8")
    return True
