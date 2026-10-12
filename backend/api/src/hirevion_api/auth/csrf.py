"""CSRF protection for cookie-authenticated requests (SP-02 spec, "Sign-in, sessions and CSRF";
ADR-0022 for the portal).

- A state-changing request carrying the session cookie must come from an allowed Origin (or,
  without one, a same-origin Referer) and send the CSRF cookie's value in `X-CSRF-Token`.
  Another site can make the browser send the cookies, but can't read them to set the header.
- Sign-in routes need the allowed Origin even without a cookie (no logging a victim into an
  attacker's account).
- Requests without the cookie elsewhere authenticate otherwise (bearer tokens) and pass.
- The candidate portal's routes (`/api/v1/portal/*`) use the candidate's own cookies and the
  portal's origins; every other route the recruiter's. Neither cookie counts on the other side.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.requests import cookie_parser
from starlette.types import ASGIApp, Receive, Scope, Send

from hirevion_api.auth.cookies import CSRF_COOKIE, SESSION_COOKIE
from hirevion_api.portal.cookies import PORTAL_CSRF_COOKIE, PORTAL_SESSION_COOKIE
from hirevion_api.problems import problem_response
from hirevion_api.routing import API_PREFIX

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
PORTAL_PREFIX = f"{API_PREFIX}/portal/"
_REFUSAL = (
    "csrf-failed",
    "Request refused",
    "This request didn't come from the Hirevion app. Reload the page and try again.",
)


@dataclass(frozen=True, slots=True)
class _Side:
    session_cookie: str
    csrf_cookie: str
    sign_in_prefix: str
    origins: frozenset[str]


def _origin_of(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else None


class CsrfMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        allowed_origins: frozenset[str],
        portal_origins: frozenset[str] = frozenset(),
    ) -> None:
        self.app = app
        self.recruiter = _Side(SESSION_COOKIE, CSRF_COOKIE, f"{API_PREFIX}/auth/", allowed_origins)
        self.portal = _Side(
            PORTAL_SESSION_COOKIE, PORTAL_CSRF_COOKIE, f"{PORTAL_PREFIX}auth/", portal_origins
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in SAFE_METHODS:
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]
        side = self.portal if path.startswith(PORTAL_PREFIX) else self.recruiter
        headers = Headers(scope=scope)
        cookies = cookie_parser(headers.get("cookie", ""))
        signed_in = side.session_cookie in cookies
        if not signed_in and not path.startswith(side.sign_in_prefix):
            await self.app(scope, receive, send)
            return

        origin = headers.get("origin") or _origin_of(headers.get("referer"))
        refused = origin not in side.origins
        if signed_in and not refused:
            sent = headers.get("x-csrf-token", "")
            expected = cookies.get(side.csrf_cookie, "")
            refused = not sent or not expected or not hmac.compare_digest(sent, expected)
        if refused:
            await problem_response(403, *_REFUSAL, instance=path)(scope, receive, send)
            return
        await self.app(scope, receive, send)
