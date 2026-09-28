"""LiveKit helpers for local development: access tokens, the third-eye phone link, and the
Cloudflare quick tunnel that makes the phone page reachable over HTTPS."""

from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote

import jwt

# A quick-tunnel address: https://<word>-<word>-...trycloudflare.com, followed by whitespace,
# the banner's "|" border or the end of the line (never a longer host name or a path).
_TUNNEL_URL = re.compile(r"https://[a-z0-9]+(?:-[a-z0-9]+)+\.trycloudflare\.com(?=[\s|]|$)")


@dataclass(frozen=True)
class Grants:
    room: str
    can_publish: bool
    can_subscribe: bool
    can_publish_data: bool
    sources: tuple[str, ...] = ()

    @classmethod
    def camera_only(cls, room: str) -> Grants:
        """The third-eye phone: publish its camera; receive and send nothing else."""
        return cls(
            room, can_publish=True, can_subscribe=False, can_publish_data=False, sources=("camera",)
        )

    @classmethod
    def participant(cls, room: str) -> Grants:
        return cls(room, can_publish=True, can_subscribe=True, can_publish_data=True)

    def video_claims(self) -> dict[str, object]:
        claims: dict[str, object] = {
            "room": self.room,
            "roomJoin": True,
            "canPublish": self.can_publish,
            "canSubscribe": self.can_subscribe,
            "canPublishData": self.can_publish_data,
        }
        if self.sources:
            claims["canPublishSources"] = list(self.sources)
        return claims


def build_token(
    api_key: str,
    api_secret: str,
    *,
    identity: str,
    name: str,
    grants: Grants,
    ttl_seconds: int,
    now: int,
) -> str:
    """A LiveKit access token (HS256 JWT) valid from `now` for `ttl_seconds`."""
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be positive")
    claims = {
        "iss": api_key,
        "sub": identity,
        "name": name,
        "nbf": now,
        "exp": now + ttl_seconds,
        "video": grants.video_claims(),
    }
    return jwt.encode(claims, api_secret, algorithm="HS256")


def parse_tunnel_url(line: str) -> str | None:
    """The quick-tunnel address in a line of cloudflared output, if there is one."""
    match = _TUNNEL_URL.search(line)
    return match.group(0) if match else None


def phone_link(tunnel_url: str, token: str) -> str:
    """The third-eye page with its token in the URL fragment, which browsers never send to a
    server (so the token stays out of Cloudflare, Caddy and Vite logs)."""
    return f"{tunnel_url.rstrip('/')}/#t={quote(token, safe='')}"


def is_lan_ip(value: str) -> bool:
    """True for a private IPv4 address a phone on the same Wi-Fi could reach."""
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return (
        address.version == 4
        and address.is_private
        and not address.is_loopback
        and not address.is_link_local
    )


def detect_lan_ip(probe: Callable[[], str]) -> str | None:
    """This PC's LAN address according to `probe`, or None."""
    try:
        address = probe()
    except OSError:
        return None
    return address if is_lan_ip(address) else None


def route_probe() -> str:
    """The local address of the route to the internet. Connecting a UDP socket sends nothing."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect(("8.8.8.8", 80))
        return str(sock.getsockname()[0])
