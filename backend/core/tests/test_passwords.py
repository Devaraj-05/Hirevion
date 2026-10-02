"""The password policy and argon2id hashing (SP-02 spec, "Passwords")."""

import asyncio
import time

from argon2 import PasswordHasher

from hirevion_core.identity.breach import BreachChecker
from hirevion_core.identity.passwords import (
    DUMMY_HASH,
    PasswordPolicy,
    hash_password,
    hash_password_in_thread,
    verify_password,
    verify_password_in_thread,
)

CONTEXT = {"email": "ravi.kumar@acme.example.test", "name": "Ravi Kumar", "organization": "Acme"}
GOOD = "correct horse battery staple"


class NeverBreached(BreachChecker):
    async def is_breached(self, password: str) -> bool:
        return False


class AlwaysBreached(BreachChecker):
    async def is_breached(self, password: str) -> bool:
        return True


async def test_a_long_unusual_password_is_accepted() -> None:
    assert await PasswordPolicy(NeverBreached()).check(GOOD, **CONTEXT) == []


async def test_length_counts_characters_after_normalisation() -> None:
    policy = PasswordPolicy(NeverBreached())
    assert await policy.check("a" * 14, **CONTEXT) == ["too_short"]
    assert await policy.check("a" * 129, **CONTEXT) == ["too_long"]
    # NFKC turns the ligature "ﬁ" into "fi": 8 ligatures are 16 characters.
    assert await policy.check("ﬁ" * 8, **CONTEXT) == []


async def test_the_users_own_details_are_refused() -> None:
    policy = PasswordPolicy(NeverBreached())
    assert await policy.check("my RAVI.KUMAR password!", **CONTEXT) == ["personal"]
    assert await policy.check("ravi kumar loves cricket", **CONTEXT) == ["personal"]
    assert await policy.check("we all work at acme here", **CONTEXT) == ["personal"]


async def test_short_details_are_not_held_against_the_password() -> None:
    context = {"email": "al@x.example.test", "name": "Al", "organization": "Xy"}
    assert await PasswordPolicy(NeverBreached()).check("totally unrelated words", **context) == []


async def test_a_breached_password_is_refused() -> None:
    assert await PasswordPolicy(AlwaysBreached()).check(GOOD, **CONTEXT) == ["breached"]


def test_hashes_are_argon2id_and_verify() -> None:
    stored = hash_password(GOOD)
    assert stored.startswith("$argon2id$")
    assert verify_password(stored, GOOD) == (True, False)
    assert verify_password(stored, GOOD + "!") == (False, False)


def test_the_same_password_hashes_to_the_same_value_after_normalisation() -> None:
    stored = hash_password("ﬁ" * 8)
    assert verify_password(stored, "fi" * 8) == (True, False)


def test_a_weaker_hash_asks_to_be_rehashed() -> None:
    weak = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash(GOOD)
    assert verify_password(weak, GOOD) == (True, True)


def test_a_missing_hash_never_verifies_but_still_takes_the_time() -> None:
    started = time.perf_counter()
    assert verify_password(None, GOOD) == (False, False)
    missing = time.perf_counter() - started

    stored = hash_password(GOOD)
    started = time.perf_counter()
    verify_password(stored, "wrong password entirely")
    real = time.perf_counter() - started

    assert DUMMY_HASH.startswith("$argon2id$")
    # Same work either way, so a response time doesn't reveal whether the account exists.
    assert missing > real / 3


async def test_hashing_and_checking_leave_the_event_loop_free() -> None:
    # argon2id takes about 100 ms; on the event loop it would stall every other request.
    ticks = 0

    async def tick() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.002)
            ticks += 1

    ticker = asyncio.create_task(tick())
    stored = await hash_password_in_thread("correct horse battery staple")
    assert await verify_password_in_thread(stored, "correct horse battery staple") == (True, False)
    ticker.cancel()
    assert ticks >= 10
