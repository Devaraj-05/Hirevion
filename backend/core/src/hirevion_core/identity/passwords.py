"""The password policy and argon2id hashing (SP-02 spec, "Passwords").

NIST SP 800-63B-4: length is what counts, so there are no composition rules. 15 characters is
its minimum for single-factor passwords; it can drop once MFA arrives (SP-19). Passwords are
NFKC-normalised before they are checked or hashed, so the same text typed on different
keyboards is the same password.
"""

from __future__ import annotations

import asyncio
import unicodedata
from contextlib import suppress
from typing import Literal

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from hirevion_core.identity.breach import BreachChecker

PasswordProblem = Literal["too_short", "too_long", "personal", "breached"]

# Personal details shorter than this are too common to hold against a password.
_MIN_DETAIL_LENGTH = 4

_hasher = PasswordHasher()
# Verified against when the account doesn't exist, so the answer takes the same time.
DUMMY_HASH = _hasher.hash("hirevion: no such account")


def normalise(password: str) -> str:
    return unicodedata.normalize("NFKC", password)


class PasswordPolicy:
    def __init__(
        self, breaches: BreachChecker, min_length: int = 15, max_length: int = 128
    ) -> None:
        self._breaches = breaches
        self.min_length = min_length
        self.max_length = max_length

    async def check(
        self, password: str, *, email: str, name: str, organization: str
    ) -> list[PasswordProblem]:
        """Every reason to refuse `password`; empty when it is acceptable."""
        candidate = normalise(password)
        problems: list[PasswordProblem] = []
        if len(candidate) < self.min_length:
            problems.append("too_short")
        elif len(candidate) > self.max_length:
            problems.append("too_long")
        if _contains_personal_detail(candidate, email=email, name=name, organization=organization):
            problems.append("personal")
        # The breach check may call out over the network, so only for an otherwise good password.
        if not problems and await self._breaches.is_breached(candidate):
            problems.append("breached")
        return problems


def _contains_personal_detail(password: str, *, email: str, name: str, organization: str) -> bool:
    lowered = password.lower()
    details = (email, email.partition("@")[0], name, organization)
    return any(
        len(detail) >= _MIN_DETAIL_LENGTH and normalise(detail).lower() in lowered
        for detail in details
    )


def hash_password(password: str) -> str:
    return _hasher.hash(normalise(password))


def verify_password(stored: str | None, password: str) -> tuple[bool, bool]:
    """(valid, needs_rehash). A missing hash still costs one verification, then fails."""
    candidate = normalise(password)
    if stored is None:
        with suppress(VerificationError, InvalidHashError):
            _hasher.verify(DUMMY_HASH, candidate)
        return False, False
    try:
        _hasher.verify(stored, candidate)
    except (VerificationError, InvalidHashError):
        return False, False
    return True, _hasher.check_needs_rehash(stored)


async def hash_password_in_thread(password: str) -> str:
    """`hash_password` on a worker thread: argon2id takes about 100 ms and releases the GIL, so
    the event loop keeps serving other requests meanwhile."""
    return await asyncio.to_thread(hash_password, password)


async def verify_password_in_thread(stored: str | None, password: str) -> tuple[bool, bool]:
    """`verify_password` on a worker thread, for the same reason."""
    return await asyncio.to_thread(verify_password, stored, password)
