"""Export Caddy's local root certificate and trust it for the current Windows user."""

from __future__ import annotations

from pathlib import Path

from .stack import compose_command

CA_CONTAINER_PATH = "/data/caddy/pki/authorities/local/root.crt"
LOCAL_CA_PATH = Path("infrastructure/local/data/caddy-root.crt")


def export_ca_command(repo_root: Path) -> list[str]:
    return compose_command(
        repo_root, ["edge"], "cp", f"caddy:{CA_CONTAINER_PATH}", str(repo_root / LOCAL_CA_PATH)
    )


def trust_ca_command(cert: Path) -> list[str]:
    """Adds the certificate to the current user's Root store (Windows asks for confirmation)."""
    return ["certutil", "-user", "-addstore", "Root", str(cert)]
