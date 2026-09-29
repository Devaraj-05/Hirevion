from datetime import UTC, datetime

from hirevion_core.ids import uuid7, uuid7_time

MS = 1_790_600_000_123  # 2026-09-28T12:53:20.123Z


def test_version_and_variant_follow_rfc_9562() -> None:
    value = uuid7()
    assert value.version == 7
    assert value.variant == "specified in RFC 4122"


def test_timestamp_round_trips() -> None:
    value = uuid7(now_ms=MS)
    assert uuid7_time(value) == datetime(2026, 9, 28, 12, 53, 20, 123_000, tzinfo=UTC)


def test_later_milliseconds_sort_after_earlier_ones() -> None:
    assert uuid7(now_ms=MS) < uuid7(now_ms=MS + 1)
    assert str(uuid7(now_ms=MS)) < str(uuid7(now_ms=MS + 1))


def test_fixed_randomness_gives_a_fixed_value() -> None:
    entropy = bytes(range(10))
    assert uuid7(now_ms=MS, rand=entropy) == uuid7(now_ms=MS, rand=entropy)


def test_values_are_unique() -> None:
    assert len({uuid7() for _ in range(10_000)}) == 10_000
