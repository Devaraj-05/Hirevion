from typing import Any

import jwt
import pytest

from hirevion_devcli.livekit import (
    Grants,
    build_token,
    detect_lan_ip,
    is_lan_ip,
    parse_tunnel_url,
    phone_link,
)

SECRET = "s" * 48


def decode(token: str) -> dict[str, Any]:
    claims: dict[str, Any] = jwt.decode(
        token,
        SECRET,
        algorithms=["HS256"],
        options={"verify_exp": False, "verify_nbf": False},
    )
    return claims


def test_camera_only_token_can_publish_only_a_camera() -> None:
    token = build_token(
        "key",
        SECRET,
        identity="phone",
        name="Third eye",
        grants=Grants.camera_only("spike"),
        ttl_seconds=600,
        now=1_000,
    )
    claims = decode(token)
    assert claims["iss"] == "key"
    assert claims["sub"] == "phone"
    assert claims["name"] == "Third eye"
    assert (claims["nbf"], claims["exp"]) == (1_000, 1_600)
    assert claims["video"] == {
        "room": "spike",
        "roomJoin": True,
        "canPublish": True,
        "canSubscribe": False,
        "canPublishData": False,
        "canPublishSources": ["camera"],
    }


def test_participant_token_can_publish_and_subscribe() -> None:
    token = build_token(
        "key",
        SECRET,
        identity="desktop",
        name="Desktop",
        grants=Grants.participant("spike"),
        ttl_seconds=60,
        now=0,
    )
    assert decode(token)["video"] == {
        "room": "spike",
        "roomJoin": True,
        "canPublish": True,
        "canSubscribe": True,
        "canPublishData": True,
    }


def test_token_lifetime_must_be_positive() -> None:
    with pytest.raises(ValueError, match="ttl"):
        build_token(
            "key",
            SECRET,
            identity="x",
            name="x",
            grants=Grants.participant("r"),
            ttl_seconds=0,
            now=0,
        )


BANNER = "2026-09-28T10:00:00Z INF |  https://brave-cat-lemon-tree.trycloudflare.com      |"


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (BANNER, "https://brave-cat-lemon-tree.trycloudflare.com"),
        (
            "https://brave-cat-lemon-tree.trycloudflare.com",
            "https://brave-cat-lemon-tree.trycloudflare.com",
        ),
        ("INF Requesting new quick Tunnel on trycloudflare.com...", None),
        ('ERR failed: Post "https://api.trycloudflare.com/tunnel": timeout', None),
        ("https://brave-cat.trycloudflare.com.evil.example", None),
        ("http://brave-cat.trycloudflare.com", None),
    ],
)
def test_parse_tunnel_url_finds_only_the_quick_tunnel_address(
    line: str, expected: str | None
) -> None:
    assert parse_tunnel_url(line) == expected


def test_phone_link_keeps_the_token_in_the_fragment() -> None:
    link = phone_link("https://brave-cat.trycloudflare.com/", "a.b-c_d")
    assert link == "https://brave-cat.trycloudflare.com/#t=a.b-c_d"


def test_phone_link_escapes_the_token() -> None:
    link = phone_link("https://brave-cat.trycloudflare.com", "a+b/c=")
    assert link == "https://brave-cat.trycloudflare.com/#t=a%2Bb%2Fc%3D"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("192.168.1.20", True),
        ("10.0.0.5", True),
        ("172.16.4.1", True),
        ("172.31.255.1", True),
        ("172.32.0.1", False),
        ("127.0.0.1", False),
        ("169.254.10.1", False),
        ("8.8.8.8", False),
        ("::1", False),
        ("not-an-ip", False),
        ("", False),
    ],
)
def test_is_lan_ip_accepts_only_private_ipv4(value: str, expected: bool) -> None:
    assert is_lan_ip(value) is expected


def test_detect_lan_ip_uses_the_probe_address() -> None:
    assert detect_lan_ip(lambda: "192.168.1.9") == "192.168.1.9"


def test_detect_lan_ip_ignores_loopback_and_failures() -> None:
    def fail() -> str:
        raise OSError("network unreachable")

    assert detect_lan_ip(lambda: "127.0.0.1") is None
    assert detect_lan_ip(fail) is None
