"""The third eye's pairing rules that need no database (SP-13, PRD §52)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hirevion_core.third_eye import pairing

NOW = datetime(2026, 10, 12, 5, 0, tzinfo=UTC)
IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
)
IPHONE_CHROME = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) CriOS/129.0 Mobile/15E148 Safari/604.1"
)
ANDROID = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/129.0.0.0 Mobile Safari/537.36"
)


@pytest.mark.parametrize(
    ("agent", "expected"),
    [
        (IPHONE, "iOS 17 Safari"),
        (IPHONE_CHROME, "iOS 18 Chrome"),
        (ANDROID, "Android 14 Chrome"),
        ("curl/8.0", "Other browser"),
        ("", "Other browser"),
    ],
)
def test_the_phone_is_named_by_its_platform_and_browser(agent: str, expected: str) -> None:
    assert pairing.platform_of(agent) == expected


def test_an_unredeemed_pairing_expires_after_two_minutes() -> None:
    expires = NOW + pairing.PAIRING_TTL
    assert timedelta(minutes=2) == pairing.PAIRING_TTL
    assert pairing.public_status("issued", expires, NOW) == "issued"
    assert pairing.public_status("issued", expires, expires) == "expired"
    # Once redeemed, the clock no longer applies.
    assert pairing.public_status("connected", expires, expires + timedelta(hours=1)) == "connected"
    assert pairing.public_status("revoked", expires, NOW) == "revoked"


def test_the_qr_url_carries_the_token_in_the_fragment() -> None:
    url = pairing.qr_url("https://eye.hirevion.localhost/", "abc_DEF-123")
    assert url == "https://eye.hirevion.localhost/#t=abc_DEF-123"
    with pytest.raises(ValueError, match="https"):
        pairing.qr_url("http://eye.example.test", "abc")


def test_secrets_are_long_random_and_stored_only_as_hashes() -> None:
    first, second = pairing.new_secret(), pairing.new_secret()
    assert first != second and len(first) >= 43
    assert pairing.hash_secret(first) == pairing.hash_secret(first)
    assert len(pairing.hash_secret(first)) == 32 and pairing.hash_secret(first) != first.encode()
