"""Time-ordered UUIDv7 identifiers (RFC 9562), used as every table's primary key.

Keys generated this way sort by creation time, which keeps B-tree inserts local and makes
cursor pagination by id meaningful.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from uuid import UUID

_TIMESTAMP_MASK = 0xFFFF_FFFF_FFFF
_RAND_B_MASK = (1 << 62) - 1


def uuid7(now_ms: int | None = None, rand: bytes | None = None) -> UUID:
    """A UUIDv7: 48-bit Unix milliseconds, version 7, then 74 random bits.

    `now_ms` and `rand` (10 bytes) exist for tests; production calls take neither.
    """
    ms = time.time_ns() // 1_000_000 if now_ms is None else now_ms
    entropy = os.urandom(10) if rand is None else rand
    value = (ms & _TIMESTAMP_MASK) << 80
    value |= 0x7 << 76
    value |= (int.from_bytes(entropy[:2], "big") & 0x0FFF) << 64
    value |= 0b10 << 62
    value |= int.from_bytes(entropy[2:10], "big") & _RAND_B_MASK
    return UUID(int=value)


def uuid7_time(value: UUID) -> datetime:
    """The creation time encoded in a UUIDv7."""
    ms = value.int >> 80
    seconds, millis = divmod(ms, 1_000)
    return datetime.fromtimestamp(seconds, tz=UTC).replace(microsecond=millis * 1_000)
