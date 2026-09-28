"""Hosts-file entries for the *.hirevion.localhost development sites.

Browsers resolve *.localhost on their own, but Windows does not, so Python, Node
and Rust clients need these entries.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

DOMAIN = "hirevion.localhost"
SUBDOMAINS: tuple[str, ...] = (
    "app",
    "candidate",
    "api",
    "ws",
    "eye",
    "livekit",
    "storage",
    "mail",
    "grafana",
    "errors",
    "downloads",
)
BEGIN = "# BEGIN hirevion (managed by `hv hosts`)"
END = "# END hirevion"
HOSTS_PATH = Path(r"C:\Windows\System32\drivers\etc\hosts")

Resolver = Callable[[str, int], Sequence[tuple[Any, ...]]]


def hostnames() -> list[str]:
    return [f"{name}.{DOMAIN}" for name in SUBDOMAINS]


def render_block(names: Sequence[str]) -> str:
    return "\n".join([BEGIN, *(f"127.0.0.1 {name}" for name in names), END]) + "\n"


def apply_block(hosts_text: str, block: str) -> str:
    """Insert or replace the managed block; every other line is kept as it was."""
    lines = hosts_text.splitlines()
    block_lines = block.splitlines()
    if BEGIN in lines and END in lines[lines.index(BEGIN) :]:
        start = lines.index(BEGIN)
        end = lines.index(END, start)
        lines = [*lines[:start], *block_lines, *lines[end + 1 :]]
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(block_lines)
    return "\r\n".join(lines) + "\r\n"


def ensure_hosts(
    hosts_path: Path,
    staging_dir: Path,
    copy: Callable[[Path, Path], int],
    resolve: Resolver = socket.getaddrinfo,
) -> list[str]:
    """Make every Hirevion hostname resolve locally; returns the names that still don't.

    `copy` replaces the hosts file with the staged content; on Windows it runs elevated.
    """
    names = hostnames()
    if not unresolved(names, resolve):
        return []
    current = hosts_path.read_text(encoding="utf-8", errors="replace")
    staged = staging_dir / "hirevion-hosts"
    staged.write_bytes(apply_block(current, render_block(names)).encode("utf-8"))
    copy(staged, hosts_path)
    return unresolved(names, resolve)


def unresolved(names: Sequence[str], resolve: Resolver = socket.getaddrinfo) -> list[str]:
    missing: list[str] = []
    for name in names:
        try:
            addresses = {str(info[4][0]) for info in resolve(name, 443)}
        except OSError:
            missing.append(name)
            continue
        if not any(ipaddress.ip_address(address).is_loopback for address in addresses):
            missing.append(name)
    return missing
