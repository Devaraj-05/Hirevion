"""The breached-password check: a bundled list plus Have I Been Pwned's range API."""

import asyncio
import hashlib
import logging

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from hirevion_core.identity.breach import (
    CompositeChecker,
    HibpChecker,
    LocalListChecker,
    aiohttp_range_fetcher,
)

PASSWORD = "a breached passphrase 2024"  # noqa: S105 (a test input)
SHA1 = hashlib.sha1(PASSWORD.encode()).hexdigest().upper()  # noqa: S324 (HIBP's format)


def range_body(*, breached: bool) -> str:
    lines = ["0018A45C4D1DEF81644B54AB7F969B88D65:1", f"{'F' * 35}:0"]
    if breached:
        lines.append(f"{SHA1[5:]}:42")
    return "\r\n".join(lines)


async def test_the_local_list_ignores_case() -> None:
    checker = LocalListChecker.from_package()
    assert await checker.is_breached("PASSWORD1") is True
    assert await checker.is_breached("PassWord1") is True
    assert await checker.is_breached("an unusual sentence nobody types") is False


async def test_hibp_receives_only_the_prefix_and_matches_the_suffix() -> None:
    asked: list[str] = []

    async def fetch(prefix: str) -> str:
        asked.append(prefix)
        return range_body(breached=True)

    assert await HibpChecker(fetch).is_breached(PASSWORD) is True
    assert asked == [SHA1[:5]]


async def test_padding_lines_are_not_matches() -> None:
    async def fetch(prefix: str) -> str:
        return f"{SHA1[5:]}:0"

    assert await HibpChecker(fetch).is_breached(PASSWORD) is False


async def test_without_hibp_the_local_list_still_applies(caplog: pytest.LogCaptureFixture) -> None:
    async def unreachable(prefix: str) -> str:
        raise aiohttp.ClientConnectionError("no route")

    checker = CompositeChecker(LocalListChecker.from_package(), HibpChecker(unreachable))
    with caplog.at_level(logging.WARNING):
        assert await checker.is_breached("PASSWORD1") is True
        assert await checker.is_breached(PASSWORD) is False
    assert len(caplog.records) == 1
    assert PASSWORD not in caplog.text and SHA1 not in caplog.text


async def test_a_slow_hibp_counts_as_unreachable() -> None:
    async def slow(prefix: str) -> str:
        await asyncio.sleep(5)
        return range_body(breached=True)

    checker = CompositeChecker(LocalListChecker.from_package(), HibpChecker(slow, timeout=0.05))
    assert await checker.is_breached(PASSWORD) is False


async def test_the_real_fetcher_asks_for_padding() -> None:
    seen: dict[str, str] = {}

    async def handle(request: web.Request) -> web.Response:
        seen["path"] = request.path
        seen["padding"] = request.headers.get("Add-Padding", "")
        seen["agent"] = request.headers.get("User-Agent", "")
        return web.Response(text=range_body(breached=False))

    app = web.Application()
    app.router.add_get("/range/{prefix}", handle)
    async with TestServer(app) as server, aiohttp.ClientSession() as session:
        fetch = aiohttp_range_fetcher(session, base_url=str(server.make_url("/range/")))
        assert await HibpChecker(fetch).is_breached(PASSWORD) is False

    assert seen["path"] == f"/range/{SHA1[:5]}"
    assert seen["padding"] == "true"
    assert seen["agent"].startswith("Hirevion")
