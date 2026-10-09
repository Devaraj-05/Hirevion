"""DPoP proof-of-possession (RFC 9449) for the desktop app's requests (SP-07c; ADR-0021).

Every desktop request carries a `DPoP` header: a JWT signed by the device's own P-256 key, with
that public key in its header. A proof is accepted only when:

- it is ES256 (`typ` `dpop+jwt`) and its `jwk` is a public P-256 key that verifies its signature;
- `htm` and `htu` name this request (the URL without query or fragment; scheme, host and path);
- `iat` is within ±60 seconds of the server's clock;
- its `jti` hasn't been seen for this key in the last 5 minutes (a replay);
- with an access token, `ath` is the token's SHA-256 and the key is the one the token is bound
  to (`cnf.jkt`).

Every refusal is a `DpopError`; the API answers each with `401 dpop-invalid`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

import jwt
from jwt.algorithms import ECAlgorithm
from redis.asyncio import Redis

MAX_SKEW_SECONDS = 60
REPLAY_WINDOW_SECONDS = 300
_JTI_MAX = 64
_REQUIRED_JWK = ("kty", "crv", "x", "y")


class DpopError(Exception):
    """A proof that can't be accepted; the message says why (for logs, never for clients)."""


@dataclass(frozen=True, slots=True)
class Proof:
    jkt: str
    """The RFC 7638 thumbprint of the device key."""
    jwk: dict[str, str]
    jti: str


class ReplayCache(Protocol):
    async def first_use(self, key: str, ttl_seconds: int) -> bool: ...


class RedisReplayCache:
    """Remembers each (key, jti) for the replay window, shared by every API process."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def first_use(self, key: str, ttl_seconds: int) -> bool:
        return bool(await self._redis.set(f"dpop:jti:{key}", "1", nx=True, ex=ttl_seconds))


class MemoryReplayCache:
    """For tests and tools: one process's memory."""

    def __init__(self) -> None:
        self._seen: dict[str, float] = {}

    async def first_use(self, key: str, ttl_seconds: int) -> bool:
        now = time.monotonic()
        self._seen = {k: until for k, until in self._seen.items() if until > now}
        if key in self._seen:
            return False
        self._seen[key] = now + ttl_seconds
        return True


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def jwk_thumbprint(jwk: dict[str, Any]) -> str:
    """RFC 7638: SHA-256 over the key's required members, in lexical order, no whitespace."""
    required = {
        "EC": ("crv", "kty", "x", "y"),
        "RSA": ("e", "kty", "n"),
        "OKP": ("crv", "kty", "x"),
    }
    members = required.get(str(jwk.get("kty")))
    if members is None:
        raise DpopError("jwk: unsupported key type")
    canonical = json.dumps(
        {name: jwk[name] for name in members}, separators=(",", ":"), sort_keys=True
    )
    return b64url(hashlib.sha256(canonical.encode("utf-8")).digest())


def access_token_hash(token: str) -> str:
    """The `ath` claim for `token`."""
    return b64url(hashlib.sha256(token.encode("ascii")).digest())


def _normalised(url: str) -> tuple[str, str, str]:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    default = {"https": 443, "http": 80}.get(parts.scheme.lower())
    if parts.port and parts.port != default:
        host = f"{host}:{parts.port}"
    return parts.scheme.lower(), host, parts.path or "/"


def _public_p256(jwk: Any) -> dict[str, str]:
    if not isinstance(jwk, dict) or any(not isinstance(jwk.get(k), str) for k in _REQUIRED_JWK):
        raise DpopError("jwk: missing or malformed")
    if "d" in jwk:
        raise DpopError("jwk: holds a private key")
    if jwk["kty"] != "EC" or jwk["crv"] != "P-256":
        raise DpopError("jwk: not a P-256 key")
    return {name: str(jwk[name]) for name in _REQUIRED_JWK}


async def check_proof(
    token: str,
    *,
    method: str,
    url: str,
    replay: ReplayCache,
    now: float | None = None,
    access_token: str | None = None,
    expected_jkt: str | None = None,
) -> Proof:
    """The proof's key, if `token` is a valid DPoP proof for this request; else DpopError."""
    moment = time.time() if now is None else now
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as error:
        raise DpopError("not a JWT") from error
    if header.get("typ") != "dpop+jwt":
        raise DpopError("typ: not dpop+jwt")
    if header.get("alg") != "ES256":
        raise DpopError("alg: only ES256")
    jwk = _public_p256(header.get("jwk"))
    try:
        key = ECAlgorithm.from_jwk(json.dumps(jwk))
        claims = jwt.decode(
            token,
            key=key,  # type: ignore[arg-type]
            algorithms=["ES256"],
            options={"verify_aud": False, "verify_exp": False, "verify_iat": False},
        )
    except jwt.InvalidSignatureError as error:
        raise DpopError("signature: doesn't verify") from error
    except (jwt.PyJWTError, ValueError) as error:
        raise DpopError("signature: unreadable") from error

    jti = claims.get("jti")
    if not isinstance(jti, str) or not 0 < len(jti) <= _JTI_MAX:
        raise DpopError("jti: missing")
    if claims.get("htm") != method.upper():
        raise DpopError("htm: another method")
    htu = claims.get("htu")
    if not isinstance(htu, str) or _normalised(htu) != _normalised(url):
        raise DpopError("htu: another URL")
    iat = claims.get("iat")
    if not isinstance(iat, int | float) or abs(moment - float(iat)) > MAX_SKEW_SECONDS:
        raise DpopError("iat: outside ±60 s")

    jkt = jwk_thumbprint(jwk)
    if access_token is not None:
        ath = claims.get("ath")
        if not isinstance(ath, str) or not hmac.compare_digest(
            ath, access_token_hash(access_token)
        ):
            raise DpopError("ath: doesn't match the access token")
    if expected_jkt is not None and not hmac.compare_digest(jkt, expected_jkt):
        raise DpopError("key: not the one the token is bound to")
    if not await replay.first_use(f"{jkt}:{jti}", REPLAY_WINDOW_SECONDS):
        raise DpopError("replay: jti already used")
    return Proof(jkt=jkt, jwk=jwk, jti=jti)
