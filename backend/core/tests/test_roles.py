import base64
import hashlib
import hmac

import pytest

from hirevion_core.db.roles import scram_verifier


def test_scram_verifier_has_postgres_format() -> None:
    verifier = scram_verifier("correct horse", salt=b"0123456789abcdef")
    scheme, rest = verifier.split("$", 1)
    iterations_and_salt, keys = rest.split("$")
    iterations, salt = iterations_and_salt.split(":")
    stored_key, server_key = keys.split(":")
    assert scheme == "SCRAM-SHA-256"
    assert iterations == "4096"
    assert base64.b64decode(salt) == b"0123456789abcdef"
    assert len(base64.b64decode(stored_key)) == 32
    assert len(base64.b64decode(server_key)) == 32


def test_scram_verifier_matches_rfc_5802_derivation() -> None:
    salt = b"salt-for-testing"
    salted = hashlib.pbkdf2_hmac("sha256", b"pencil", salt, 4096)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    expected_stored = base64.b64encode(hashlib.sha256(client_key).digest()).decode()
    verifier = scram_verifier("pencil", salt=salt)
    assert verifier.split("$")[2].split(":")[0] == expected_stored


def test_scram_verifier_uses_a_fresh_salt_each_time() -> None:
    assert scram_verifier("same") != scram_verifier("same")


def test_empty_password_is_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        scram_verifier("")
