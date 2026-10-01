"""The session cookies. `__Host-` makes browsers require Secure, Path=/ and no Domain, so no
other host (a sibling subdomain included) can set or read them."""

from __future__ import annotations

from fastapi import Response

SESSION_COOKIE = "__Host-hv_session"
# Readable by the app's scripts, which repeat it in X-CSRF-Token (double submit).
CSRF_COOKIE = "__Host-hv_csrf"


def set_session_cookies(response: Response, session_token: str, csrf_token: str) -> None:
    # No Max-Age: they last the browser session, and the server enforces the real expiry.
    response.set_cookie(
        SESSION_COOKIE, session_token, httponly=True, secure=True, samesite="lax", path="/"
    )
    response.set_cookie(
        CSRF_COOKIE, csrf_token, httponly=False, secure=True, samesite="lax", path="/"
    )


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    response.delete_cookie(CSRF_COOKIE, path="/", secure=True, samesite="lax")
