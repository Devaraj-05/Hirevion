import hashlib
from datetime import UTC, datetime
from uuid import UUID

import pytest

from hirevion_core.audit import GENESIS_HASH, AuditEntry, audit_record, canonical_json, chain_hash

ORG = UUID("01920000-0000-7000-8000-000000000001")
ROW = UUID("01920000-0000-7000-8000-0000000000aa")


def test_canonical_json_ignores_key_order_and_keeps_utf8() -> None:
    first = canonical_json({"b": 1, "a": "नमस्ते", "c": {"z": True, "y": None}})
    second = canonical_json({"c": {"y": None, "z": True}, "a": "नमस्ते", "b": 1})
    assert first == second
    assert first == '{"a":"नमस्ते","b":1,"c":{"y":null,"z":true}}'.encode()


def test_canonical_json_rejects_values_jsonb_cannot_store() -> None:
    with pytest.raises(ValueError, match="Out of range float"):
        canonical_json({"score": float("nan")})


def test_chain_hash_is_sha256_of_the_previous_hash_and_the_record() -> None:
    record = {"seq": 1, "action": "user.login"}
    expected = hashlib.sha256(GENESIS_HASH + canonical_json(record)).digest()
    assert chain_hash(GENESIS_HASH, record) == expected


def test_the_genesis_hash_is_32_zero_bytes() -> None:
    assert bytes(32) == GENESIS_HASH


def test_audit_record_normalises_what_the_database_rewrites() -> None:
    entry = AuditEntry(
        action="user.login",
        resource_type="user",
        resource_id="42",
        actor_type="user",
        actor_id="7",
        ip="2001:DB8::0001",
        user_agent="AI-Interview/1.0",
        details={"method": "password"},
    )
    when = datetime(2026, 9, 29, 10, 30, 0, 0, tzinfo=UTC)
    assert audit_record(ROW, ORG, 3, when, entry) == {
        "id": str(ROW),
        "organization_id": str(ORG),
        "seq": 3,
        "occurred_at": "2026-09-29T10:30:00.000000+00:00",
        "actor_type": "user",
        "actor_id": "7",
        "action": "user.login",
        "resource_type": "user",
        "resource_id": "42",
        "ip": "2001:db8::1",
        "user_agent": "AI-Interview/1.0",
        "details": {"method": "password"},
    }


def test_audit_times_must_carry_a_time_zone() -> None:
    entry = AuditEntry(action="user.login", resource_type="user")
    with pytest.raises(ValueError, match="time zone"):
        audit_record(ROW, ORG, 1, datetime(2026, 9, 29, 10, 30), entry)
