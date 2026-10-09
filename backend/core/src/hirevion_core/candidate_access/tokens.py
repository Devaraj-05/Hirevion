"""Candidate tokens (SP-07c; ADR-0021): ES256 JWTs bound to the device key, and opaque
rotating refresh tokens.

- **Access token** (`scope` `candidate`): 10 minutes; for the sign-in endpoints, the interview
  list and asking for a session token.
- **Interview-session token** (`scope` `interview`): for one interview, until the earliest of
  the window's end plus the interview's duration, now + 4 hours and the refresh family's end.

Both carry `cnf.jkt` (the device key's thumbprint, RFC 9449) and `sid` (the refresh family), so
a request must also prove the key and the family must still be live. Refresh tokens are 256
random bits behind an `rt_` prefix; only their SHA-256 is stored.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from hirevion_core.candidate_access.dpop import b64url, jwk_thumbprint
from hirevion_core.ids import uuid7
from hirevion_core.settings import repo_env_file

log = logging.getLogger(__name__)

AUDIENCE = "hirevion-desktop"
Scope = Literal["candidate", "interview"]
REFRESH_PREFIX = "rt_"


class CandidateAuthSettings(BaseSettings):
    """`HV_CANDIDATE_*` and friends; see ADR-0021."""

    model_config = SettingsConfigDict(env_prefix="HV_", extra="ignore", hide_input_in_errors=True)

    environment: str = "development"
    # Base64 of a PKCS #8 DER P-256 private key (`hv init-env` makes one).
    candidate_token_key: SecretStr | None = None
    candidate_token_issuer: str = "https://api.hirevion.localhost"  # noqa: S105 (a URL)
    candidate_access_minutes: int = 10
    candidate_refresh_hours: int = 8
    candidate_session_hours: int = 4
    candidate_otp_minutes: int = 10
    candidate_otp_attempts: int = 5
    candidate_otp_resend_seconds: int = 60
    candidate_otp_max_sends: int = 5
    # Outside production, a missing signing key is derived from this install's database
    # password, so every API process of the install agrees on it (ADR-0021).
    postgres_app_password: SecretStr | None = Field(None, validation_alias="POSTGRES_APP_PASSWORD")

    @property
    def access_ttl(self) -> timedelta:
        return timedelta(minutes=self.candidate_access_minutes)

    @property
    def refresh_ttl(self) -> timedelta:
        return timedelta(hours=self.candidate_refresh_hours)

    @property
    def session_ttl(self) -> timedelta:
        return timedelta(hours=self.candidate_session_hours)

    @property
    def otp_ttl(self) -> timedelta:
        return timedelta(minutes=self.candidate_otp_minutes)


def load_candidate_auth_settings() -> CandidateAuthSettings:
    return CandidateAuthSettings(_env_file=repo_env_file())  # type: ignore[call-arg]


class TokenError(Exception):
    """A token that can't be accepted (bad signature, expired, wrong scope or audience)."""


@dataclass(frozen=True, slots=True)
class TokenClaims:
    account_id: UUID
    organization_id: UUID
    jkt: str
    family_id: UUID
    scope: Scope
    interview_id: UUID | None
    expires_at: datetime


def generate_key_b64() -> str:
    """A new signing key, as `HV_CANDIDATE_TOKEN_KEY` holds it."""
    key = ec.generate_private_key(ec.SECP256R1())
    der = key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return base64.b64encode(der).decode("ascii")


class TokenSigner:
    def __init__(self, key: ec.EllipticCurvePrivateKey, issuer: str) -> None:
        if not isinstance(key.curve, ec.SECP256R1):
            raise ValueError("the candidate token key must be a P-256 key")
        self._key = key
        self.issuer = issuer
        numbers = key.public_key().public_numbers()
        self.public_jwk = {
            "kty": "EC",
            "crv": "P-256",
            "x": b64url(numbers.x.to_bytes(32, "big")),
            "y": b64url(numbers.y.to_bytes(32, "big")),
        }
        self.kid = jwk_thumbprint(self.public_jwk)
        der = key.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        # A separate secret for one-time codes, derived so it changes with the signing key.
        self._otp_key = hmac.new(der, b"hirevion candidate otp", hashlib.sha256).digest()

    @classmethod
    def from_settings(cls, settings: CandidateAuthSettings) -> TokenSigner:
        if settings.candidate_token_key is not None:
            der = base64.b64decode(settings.candidate_token_key.get_secret_value())
            key = serialization.load_der_private_key(der, password=None)
            if not isinstance(key, ec.EllipticCurvePrivateKey):
                raise ValueError("HV_CANDIDATE_TOKEN_KEY isn't an elliptic-curve key")
            return cls(key, settings.candidate_token_issuer)
        if settings.environment == "production":
            raise ValueError("set HV_CANDIDATE_TOKEN_KEY: production needs a stable signing key")
        if settings.postgres_app_password is not None:
            log.warning(
                "HV_CANDIDATE_TOKEN_KEY isn't set: candidate tokens use a development key derived "
                "from this install's secrets (run `uv run hv env-sync` to add a real one)"
            )
            return cls(
                _derived_key(settings.postgres_app_password), settings.candidate_token_issuer
            )
        log.warning(
            "HV_CANDIDATE_TOKEN_KEY isn't set: candidate tokens use a key made at start-up, which "
            "only this process knows (run `uv run hv env-sync`)"
        )
        return cls(ec.generate_private_key(ec.SECP256R1()), settings.candidate_token_issuer)

    def issue(
        self,
        *,
        account_id: UUID,
        organization_id: UUID,
        jkt: str,
        family_id: UUID,
        scope: Scope,
        expires_at: datetime,
        now: datetime,
        interview_id: UUID | None = None,
    ) -> str:
        claims: dict[str, Any] = {
            "iss": self.issuer,
            "aud": AUDIENCE,
            "sub": str(account_id),
            "org": str(organization_id),
            "scope": scope,
            "cnf": {"jkt": jkt},
            "sid": str(family_id),
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
            "jti": str(uuid7()),
        }
        if interview_id is not None:
            claims["interview_id"] = str(interview_id)
        return jwt.encode(claims, self._key, algorithm="ES256", headers={"kid": self.kid})

    def verify(self, token: str, *, scope: Scope, now: datetime | None = None) -> TokenClaims:
        moment = now or datetime.now(UTC)
        try:
            claims = jwt.decode(
                token,
                key=self._key.public_key(),
                algorithms=["ES256"],
                audience=AUDIENCE,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
                leeway=0,
            )
        except jwt.PyJWTError as error:
            raise TokenError(str(error)) from error
        if claims.get("scope") != scope:
            raise TokenError("wrong scope")
        try:
            jkt = str(claims["cnf"]["jkt"])
            result = TokenClaims(
                account_id=UUID(claims["sub"]),
                organization_id=UUID(claims["org"]),
                jkt=jkt,
                family_id=UUID(claims["sid"]),
                scope=scope,
                interview_id=UUID(claims["interview_id"]) if "interview_id" in claims else None,
                expires_at=datetime.fromtimestamp(int(claims["exp"]), UTC),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise TokenError("malformed claims") from error
        if result.expires_at <= moment:
            raise TokenError("expired")
        if scope == "interview" and result.interview_id is None:
            raise TokenError("no interview")
        return result

    def otp_hash(self, challenge_id: UUID, code: str) -> bytes:
        return hmac.new(self._otp_key, f"{challenge_id}:{code}".encode(), hashlib.sha256).digest()


# The order of the P-256 group: a derived scalar must be below it (and not zero).
_P256_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551


def _derived_key(secret: SecretStr) -> ec.EllipticCurvePrivateKey:
    """A P-256 key that any process with the same secret derives the same way."""
    digest = hmac.new(
        secret.get_secret_value().encode("utf-8"),
        b"hirevion candidate token key (development)",
        hashlib.sha512,
    ).digest()
    scalar = int.from_bytes(digest, "big") % (_P256_ORDER - 1) + 1
    return ec.derive_private_key(scalar, ec.SECP256R1())


def new_refresh_token() -> tuple[str, bytes]:
    """A refresh token and the hash to store."""
    token = REFRESH_PREFIX + secrets.token_urlsafe(32)
    return token, refresh_hash(token)


def refresh_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def new_otp_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"
