"""Read and create the gitignored root .env file used for local development."""

from __future__ import annotations

import base64
import re
import secrets
from pathlib import Path

from hirevion_core.candidate_access.tokens import generate_key_b64

REQUIRED_KEYS: tuple[str, ...] = ("GEMINI_API_KEY", "DEEPGRAM_API_KEY")
GENERATED_KEYS: dict[str, int] = {
    "POSTGRES_PASSWORD": 32,
    # Passwords for the application and outbox-relay database roles (ADR-0009).
    "POSTGRES_APP_PASSWORD": 32,
    "POSTGRES_RELAY_PASSWORD": 32,
    "VALKEY_PASSWORD": 32,
    "LIVEKIT_API_SECRET": 48,
    "GLITCHTIP_SECRET_KEY": 50,
    # The password of the development users `hv seed-identity` creates (15+ characters).
    "HV_SEED_PASSWORD": 24,
}
# Values that must be standard base64 (Azure storage keys): number of random bytes.
GENERATED_BASE64_KEYS: dict[str, int] = {"AZURE_STORAGE_KEY": 64}
# Signing keys: base64 PKCS #8 P-256 private keys (the candidate tokens' key, ADR-0021).
GENERATED_SIGNING_KEYS: tuple[str, ...] = ("HV_CANDIDATE_TOKEN_KEY",)
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
    values = {key: secrets.token_urlsafe(length)[:length] for key, length in GENERATED_KEYS.items()}
    for key, size in GENERATED_BASE64_KEYS.items():
        values[key] = base64.b64encode(secrets.token_bytes(size)).decode("ascii")
    for key in GENERATED_SIGNING_KEYS:
        values[key] = generate_key_b64()
    return values


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


def sync_env(example_text: str, env_text: str, generated: dict[str, str]) -> tuple[str, list[str]]:
    """Append keys that are in the example but missing from the env text; keep existing values."""
    existing = parse_env(env_text)
    added: list[str] = []
    lines: list[str] = []
    for key, example_value in parse_env(example_text).items():
        if key in existing:
            continue
        added.append(key)
        lines.append(f"{key}={example_value or generated.get(key, '')}")
    if not added:
        return env_text, []
    base = env_text if not env_text or env_text.endswith("\n") else env_text + "\n"
    return base + "# Added by `hv env-sync`\n" + "\n".join(lines) + "\n", added


def init_env(example_path: Path, env_path: Path) -> bool:
    """Create env_path from example_path with fresh local secrets; never overwrites."""
    if env_path.exists():
        return False
    example_text = example_path.read_text(encoding="utf-8")
    env_path.write_text(render_env(example_text, generate_local_secrets()), encoding="utf-8")
    return True
