"""Rendering a report's HTML to a PDF with Playwright's Chromium (SP-17; ADR-0023).

The page runs with JavaScript off and every request refused, so a report can't reach out to
anything or run anything, whatever its text says. Chromium is a separate process started per
export (a few at once at most); if it isn't installed the export says so and the web view still
works (`uv run playwright install chromium`, or the image's own copy in production)."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from html import escape
from importlib.metadata import PackageNotFoundError, version
from typing import Protocol

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Route, async_playwright

log = logging.getLogger(__name__)

MAX_AT_ONCE = 2
RENDER_TIMEOUT_MS = 60_000


class PdfUnavailable(RuntimeError):
    """The PDF renderer isn't installed or couldn't start."""


class PdfRenderer(Protocol):
    name: str

    async def render(self, html: str, *, footer: str) -> bytes: ...


def _footer(text: str) -> str:
    return (
        '<div style="width:100%;font:7pt Arial,sans-serif;color:#6b7280;padding:0 14mm;'
        'display:flex;justify-content:space-between">'
        f"<span>{escape(text)}</span>"
        '<span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span>'
        "</div>"
    )


async def _refuse(route: Route) -> None:
    await route.abort()


class PlaywrightPdfRenderer:
    def __init__(self) -> None:
        try:
            self.name = f"chromium via playwright {version('playwright')}"
        except PackageNotFoundError:
            self.name = "chromium via playwright"
        self._slots: asyncio.Semaphore | None = None

    async def render(self, html: str, *, footer: str) -> bytes:
        args = ["--disable-gpu"]
        if getattr(os, "geteuid", lambda: 1)() == 0:  # containers run as root; Chromium needs this
            args.append("--no-sandbox")
        if self._slots is None:  # made inside the running loop
            self._slots = asyncio.Semaphore(MAX_AT_ONCE)
        async with self._slots, async_playwright() as playwright:
            try:
                browser = await playwright.chromium.launch(args=args, timeout=RENDER_TIMEOUT_MS)
            except PlaywrightError as error:
                log.warning("Chromium couldn't start for a report PDF: %s", error)
                raise PdfUnavailable(
                    "Chromium isn't available: run `uv run playwright install chromium`"
                ) from error
            try:
                context = await browser.new_context(java_script_enabled=False, offline=True)
                page = await context.new_page()
                await page.route("**/*", _refuse)
                await page.set_content(html, wait_until="load", timeout=RENDER_TIMEOUT_MS)
                return await page.pdf(
                    format="A4",
                    print_background=True,
                    display_header_footer=True,
                    header_template="<span></span>",
                    footer_template=_footer(footer),
                    margin={"top": "18mm", "bottom": "20mm", "left": "14mm", "right": "14mm"},
                )
            finally:
                await browser.close()


def footer_text(title: str, generated_at: datetime) -> str:
    return f"{title} - generated {generated_at:%d %b %Y %H:%M} UTC - Hirevion"
