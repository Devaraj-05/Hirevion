"""The pairing's rules that need no database (`docs/api/contracts/third-eye.md`).

PRD §52's five properties, and where each is kept:

- **short-lived:** a pairing must be redeemed within `PAIRING_TTL`; the phone's LiveKit token
  lives `LIVEKIT_TTL` (LiveKit refreshes it while the phone stays connected);
- **single-use:** redeeming spends the token under a row lock (`service.redeem`);
- **interview-bound** and **candidate-bound:** the pairing row holds both, and the LiveKit token
  can join only that interview's room;
- **revocable:** revoking (or pairing again) ends the pairing and removes its phone from the room.

The token is 256 bits from `secrets`, kept only as its SHA-256, and travels in the URL fragment,
which browsers never send, so it stays out of server and proxy logs.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from hirevion_core.identity.sessions import hash_token, new_token

PAIRING_TTL = timedelta(minutes=2)
LIVEKIT_TTL = timedelta(minutes=10)
USER_AGENT_MAX = 400

_IOS = re.compile(r"(?:iPhone|iPad|iPod).*?OS (\d+)[_\d]*")
_ANDROID = re.compile(r"Android (\d+)")


def new_secret() -> str:
    return new_token()


def hash_secret(secret: str) -> bytes:
    return hash_token(secret)


def platform_of(user_agent: str) -> str:
    """A short name for the phone (`iOS 17 Safari`, `Android 14 Chrome`) for the desktop and the
    recruiter; never used to decide anything."""
    agent = user_agent or ""
    if ios := _IOS.search(agent):
        system = f"iOS {ios.group(1)}"
    elif android := _ANDROID.search(agent):
        system = f"Android {android.group(1)}"
    else:
        return "Other browser"
    # Browsers built on Chrome name it too, so they are recognised first.
    if "SamsungBrowser/" in agent:
        browser = "Samsung Internet"
    elif "EdgiOS/" in agent or "EdgA/" in agent:
        browser = "Edge"
    elif "OPR/" in agent or "OPiOS/" in agent:
        browser = "Opera"
    elif "FxiOS/" in agent or "Firefox/" in agent:
        browser = "Firefox"
    elif "CriOS/" in agent or "Chrome/" in agent:
        browser = "Chrome"
    elif "Safari/" in agent:
        browser = "Safari"
    else:
        browser = "browser"
    return f"{system} {browser}"


def public_status(status: str, expires_at: datetime, now: datetime) -> str:
    """The contract's status: an issued pairing past its time is `expired`."""
    if status == "issued" and now >= expires_at:
        return "expired"
    return status


def qr_url(base: str, token: str) -> str:
    """The phone page's URL with the token in its fragment (`https://eye.../#t=<token>`)."""
    if not base.startswith("https://"):
        raise ValueError("the third-eye page must be served over https (phones need it)")
    return f"{base.rstrip('/')}/#t={token}"
