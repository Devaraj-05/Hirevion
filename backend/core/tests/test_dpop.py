"""DPoP proofs (RFC 9449; SP-07c Task 2): what the server accepts and every way it refuses."""

import base64
import hashlib
import json
import time
import uuid
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from hirevion_core.candidate_access.dpop import (
    DpopError,
    MemoryReplayCache,
    check_proof,
    jwk_thumbprint,
)

URL = "https://api.hirevion.localhost/api/v1/candidate-auth/login"


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def public_jwk(key: ec.EllipticCurvePrivateKey) -> dict[str, str]:
    numbers = key.public_key().public_numbers()
    return {
        "kty": "EC",
        "crv": "P-256",
        "x": b64(numbers.x.to_bytes(32, "big")),
        "y": b64(numbers.y.to_bytes(32, "big")),
    }


def proof(
    key: Any,
    *,
    method: str = "POST",
    url: str = URL,
    iat: float | None = None,
    jti: str | None = None,
    ath: str | None = None,
    header: dict[str, Any] | None = None,
    alg: str = "ES256",
    jwk: dict[str, Any] | None = None,
) -> str:
    claims: dict[str, Any] = {
        "jti": jti or str(uuid.uuid4()),
        "htm": method,
        "htu": url,
        "iat": int(iat if iat is not None else time.time()),
    }
    if ath is not None:
        claims["ath"] = ath
    headers = {"typ": "dpop+jwt", "jwk": jwk if jwk is not None else public_jwk(key)}
    headers.update(header or {})
    return jwt.encode(claims, key, algorithm=alg, headers=headers)


@pytest.fixture
def key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


async def check(token: str, **overrides: Any) -> Any:
    arguments: dict[str, Any] = {
        "method": "POST",
        "url": URL,
        "replay": MemoryReplayCache(),
        "now": time.time(),
    }
    arguments.update(overrides)
    return await check_proof(token, **arguments)


def test_the_thumbprint_is_rfc_7638() -> None:
    # RFC 7638 §3.1's example key.
    jwk = {
        "kty": "RSA",
        "n": (
            "0vx7agoebGcQSuuPiLJXZptN9nndrQmbXEps2aiAFbWhM78LhWx4cbbfAAtVT86zwu1RK7aPFFxuhDR1L6tSo"
            "c_BJECPebWKRXjBZCiFV4n3oknjhMstn64tZ_2W-5JsGY4Hc5n9yBXArwl93lqt7_RN5w6Cf0h4QyQ5v-65YGj"
            "QR0_FDW2QvzqY368QQMicAtaSqzs8KJZgnYb9c7d0zgdAZHzu6qMQvRL5hajrn1n91CbOpbISD08qNLyrdkt-"
            "bFTWhAI4vMQFh6WeZu0fM4lFd2NcRwr3XPksINHaQ-G_xBniIqbw0Ls1jF44-csFCur-kEgU8awapJzKnqDKg"
            "w"
        ),
        "e": "AQAB",
    }
    assert jwk_thumbprint(jwk) == "NzbLsXh8uDCcd-6MNwXF4W_7noWXFZAfHkxZsRGC9Xs"


async def test_a_good_proof_names_its_key(key: ec.EllipticCurvePrivateKey) -> None:
    result = await check(proof(key))
    assert result.jkt == jwk_thumbprint(public_jwk(key))
    assert result.jwk == public_jwk(key)


async def test_the_url_is_compared_without_query_and_case_insensitively_on_the_host(
    key: ec.EllipticCurvePrivateKey,
) -> None:
    signed = proof(key, url="https://API.hirevion.localhost/api/v1/candidate-auth/login")
    await check(signed, url=URL + "?x=1")


@pytest.mark.parametrize(
    ("change", "why"),
    [
        ({"method": "GET"}, "htm"),
        ({"url": "https://api.hirevion.localhost/api/v1/candidate-auth/refresh"}, "htu"),
        ({"url": "http://api.hirevion.localhost/api/v1/candidate-auth/login"}, "htu"),
        ({"iat": -120}, "iat"),
        ({"iat": 120}, "iat"),
    ],
)
async def test_a_proof_for_another_request_or_time_is_refused(
    key: ec.EllipticCurvePrivateKey, change: dict[str, Any], why: str
) -> None:
    if "iat" in change:
        # Seconds from now, taken when the test runs (not when it was collected).
        change = {"iat": time.time() + change["iat"]}
    with pytest.raises(DpopError, match=why):
        await check(proof(key, **change))


async def test_a_replayed_proof_is_refused(key: ec.EllipticCurvePrivateKey) -> None:
    replay = MemoryReplayCache()
    signed = proof(key)
    await check(signed, replay=replay)
    with pytest.raises(DpopError, match="replay"):
        await check(signed, replay=replay)


async def test_only_es256_with_a_public_p256_key_is_accepted(
    key: ec.EllipticCurvePrivateKey,
) -> None:
    other = ec.generate_private_key(ec.SECP384R1())
    with pytest.raises(DpopError):
        await check(proof(other, alg="ES384", jwk={**public_jwk(key)}))
    private = {**public_jwk(key), "d": b64(b"secret")}
    with pytest.raises(DpopError, match="jwk"):
        await check(proof(key, jwk=private))
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(DpopError):
        await check(proof(rsa_key, alg="RS256", jwk={"kty": "RSA", "n": "x", "e": "AQAB"}))
    with pytest.raises(DpopError, match="typ"):
        await check(proof(key, header={"typ": "JWT"}))


async def test_a_proof_signed_by_another_key_is_refused(key: ec.EllipticCurvePrivateKey) -> None:
    thief = ec.generate_private_key(ec.SECP256R1())
    # Signed by the thief, but naming the victim's public key.
    with pytest.raises(DpopError, match="signature"):
        await check(proof(thief, jwk=public_jwk(key)))


async def test_with_an_access_token_the_proof_must_hash_it_and_use_its_key(
    key: ec.EllipticCurvePrivateKey,
) -> None:
    access = "eyJ.example.token"
    ath = b64(hashlib.sha256(access.encode()).digest())
    jkt = jwk_thumbprint(public_jwk(key))
    await check(proof(key, ath=ath), access_token=access, expected_jkt=jkt)
    with pytest.raises(DpopError, match="ath"):
        await check(proof(key), access_token=access, expected_jkt=jkt)
    with pytest.raises(DpopError, match="ath"):
        await check(proof(key, ath=b64(b"x" * 32)), access_token=access, expected_jkt=jkt)
    with pytest.raises(DpopError, match="key"):
        await check(proof(key, ath=ath), access_token=access, expected_jkt="someone-else")


async def test_garbage_is_refused() -> None:
    for token in ("", "not-a-jwt", "a.b.c", json.dumps({"typ": "dpop+jwt"})):
        with pytest.raises(DpopError):
            await check(token)


def test_a_development_key_is_the_same_in_every_process_of_an_install() -> None:
    from pydantic import SecretStr

    from hirevion_core.candidate_access.tokens import CandidateAuthSettings, TokenSigner

    settings = CandidateAuthSettings(
        environment="development",
        candidate_token_key=None,
        postgres_app_password=SecretStr("an install's database password"),
    )
    assert TokenSigner.from_settings(settings).kid == TokenSigner.from_settings(settings).kid
    other = settings.model_copy(update={"postgres_app_password": SecretStr("another install")})
    assert TokenSigner.from_settings(other).kid != TokenSigner.from_settings(settings).kid
    with pytest.raises(ValueError, match="production"):
        TokenSigner.from_settings(settings.model_copy(update={"environment": "production"}))
