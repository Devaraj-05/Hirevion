"""CSRF protection for cookie-authenticated requests (SP-02 spec, "Sign-in, sessions and CSRF").

- A state-changing request carrying the session cookie must come from an allowed Origin (or,
  without one, a same-origin Referer) and send the CSRF cookie's value in `X-CSRF-Token`.
  Another site can make the browser send the cookies, but can't read them to set the header.
- Sign-in routes need the allowed Origin even without a cookie (no logging a victim into an
  attacker's account).
- Requests without the cookie elsewhere authenticate otherwise (bearer tokens) and pass.
"""

from __future__ import annotations

import hmac
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.requests import cookie_parser
from starlette.types import ASGIApp, Receive, Scope, Send

from hirevion_api.auth.cookies import CSRF_COOKIE, SESSION_COOKIE
from hirevion_api.problems import problem_response
from hirevion_api.routing import API_PREFIX

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_SIGN_IN_PREFIX = f"{API_PREFIX}/auth/"
_REFUSAL = (
    "csrf-failed",
    "Request refused",
    "This request didn't come from the Hirevion app. Reload the page and try again.",
)


def _origin_of(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else None


class CsrfMiddleware:
    def __init__(self, app: ASGIApp, allowed_origins: frozenset[str]) -> None:
        self.app = app
        self.allowed_origins = allowed_origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in SAFE_METHODS:
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        cookies = cookie_parser(headers.get("cookie", ""))
        signed_in = SESSION_COOKIE in cookies
        if not signed_in and not scope["path"].startswith(_SIGN_IN_PREFIX):
            await self.app(scope, receive, send)
            return

        origin = headers.get("origin") or _origin_of(headers.get("referer"))
        refused = origin not in self.allowed_origins
        if signed_in and not refused:
            sent = headers.get("x-csrf-token", "")
            expected = cookies.get(CSRF_COOKIE, "")
            refused = not sent or not expected or not hmac.compare_digest(sent, expected)
        if refused:
            await problem_response(403, *_REFUSAL, instance=scope["path"])(scope, receive, send)
            return
        await self.app(scope, receive, send)
