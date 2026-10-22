"""The breached-password check (SP-02 spec, "Passwords").

A bundled list of common passwords always applies. Have I Been Pwned's range API is asked when
it can be reached: it receives only the first 5 hex characters of the password's SHA-1 and
returns every suffix with that prefix (padded with fake ones), so the password never leaves us.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from functools import cache
from importlib.resources import files
from typing import Protocol

import aiohttp

log = logging.getLogger(__name__)

HIBP_RANGE_URL = "https://api.pwnedpasswords.com/range/"
USER_AGENT = "Hirevion password check"

RangeFetch = Callable[[str], Awaitable[str]]


class BreachChecker(Protocol):
    async def is_breached(self, password: str) -> bool: ...


@cache
def _package_list() -> frozenset[str]:
    text = files("hirevion_core.identity").joinpath("data/common-passwords.txt").read_text("utf-8")
    return frozenset(line for line in text.splitlines() if line)


class LocalListChecker:
    """The bundled list (see `data/README.md`), compared case-insensitively."""

    def __init__(self, words: frozenset[str]) -> None:
        self._words = words

    @classmethod
    def from_package(cls) -> LocalListChecker:
        return cls(_package_list())

    async def is_breached(self, password: str) -> bool:
        return password.lower() in self._words


class HibpChecker:
    """Have I Been Pwned's range API. Raises when it can't answer within `timeout` seconds."""

    def __init__(self, fetch: RangeFetch, timeout: float = 2.0) -> None:
        self._fetch = fetch
        self._timeout = timeout

    async def is_breached(self, password: str) -> bool:
        # Have I Been Pwned's range API is keyed by SHA-1; only the first five characters leave
        # this process, and nothing here depends on SHA-1 being collision resistant.
        # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1
        digest = hashlib.sha1(password.encode("utf-8"), usedforsecurity=False).hexdigest().upper()
        prefix, suffix = digest[:5], digest[5:]
        body = await asyncio.wait_for(self._fetch(prefix), self._timeout)
        for line in body.splitlines():
            candidate, _, count = line.strip().partition(":")
            # Padding lines carry a count of 0.
            if candidate == suffix and count.strip() not in ("", "0"):
                return True
        return False


class CompositeChecker:
    """The local list, then the remote service; if the service fails, the list's answer stands."""

    def __init__(self, local: BreachChecker, remote: BreachChecker | None = None) -> None:
        self._local = local
        self._remote = remote

    async def is_breached(self, password: str) -> bool:
        if await self._local.is_breached(password):
            return True
        if self._remote is None:
            return False
        try:
            return await self._remote.is_breached(password)
        except (TimeoutError, aiohttp.ClientError, OSError):
            log.warning("The breached-password service didn't answer; only the local list applied")
            return False


def aiohttp_range_fetcher(
    session: aiohttp.ClientSession, base_url: str = HIBP_RANGE_URL
) -> RangeFetch:
    async def fetch(prefix: str) -> str:
        headers = {"Add-Padding": "true", "User-Agent": USER_AGENT}
        async with session.get(f"{base_url}{prefix}", headers=headers) as response:
            response.raise_for_status()
            return await response.text()

    return fetch
