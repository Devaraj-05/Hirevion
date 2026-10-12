"""The candidate portal's cookies (ADR-0022): named apart from the recruiter's, so neither one
ever works on the other's routes, even where both hosts are one (`next dev` on localhost).
`__Host-` keeps them on the portal's own host."""

from __future__ import annotations

from fastapi import Response

PORTAL_SESSION_COOKIE = "__Host-hv_candidate_session"
# Readable by the portal's scripts, which repeat it in X-CSRF-Token (double submit).
PORTAL_CSRF_COOKIE = "__Host-hv_candidate_csrf"


def set_portal_cookies(response: Response, session_token: str, csrf_token: str) -> None:
    # No Max-Age: they last the browser session, and the server enforces the real expiry.
    response.set_cookie(
        PORTAL_SESSION_COOKIE, session_token, httponly=True, secure=True, samesite="lax", path="/"
    )
    response.set_cookie(
        PORTAL_CSRF_COOKIE, csrf_token, httponly=False, secure=True, samesite="lax", path="/"
    )


def clear_portal_cookies(response: Response) -> None:
    response.delete_cookie(
        PORTAL_SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax"
    )
    response.delete_cookie(PORTAL_CSRF_COOKIE, path="/", secure=True, samesite="lax")
