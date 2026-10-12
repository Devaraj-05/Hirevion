"""The portal's auth service and session, as route dependencies (ADR-0022)."""

from __future__ import annotations

import hmac
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request

from hirevion_api.auth.csrf import SAFE_METHODS
from hirevion_api.deps import get_db, get_redis
from hirevion_api.portal.cookies import PORTAL_CSRF_COOKIE, PORTAL_SESSION_COOKIE
from hirevion_api.problems import ProblemError
from hirevion_core.candidate_portal.auth import PortalAuthService
from hirevion_core.candidate_portal.sessions import PortalSession, resolve_portal_session
from hirevion_core.identity.sessions import hash_token


def portal_auth_service(request: Request) -> PortalAuthService:
    state = request.app.state
    return PortalAuthService(
        get_db(request),
        get_redis(request),
        policy=state.candidate_password_policy,
        settings=state.identity,
    )


async def optional_portal_session(request: Request) -> PortalSession | None:
    """The live portal session from the candidate's cookie, or None. On a state-changing
    request the CSRF cookie must also belong to this session (the middleware has checked it
    matches the header)."""
    token = request.cookies.get(PORTAL_SESSION_COOKIE)
    if not token:
        return None
    context = await resolve_portal_session(
        get_db(request), token, settings=request.app.state.identity, now=datetime.now(UTC)
    )
    if context is None:
        return None
    if request.method not in SAFE_METHODS:
        csrf = request.cookies.get(PORTAL_CSRF_COOKIE, "")
        if not hmac.compare_digest(hash_token(csrf), context.csrf_hash):
            raise ProblemError(403, "csrf-failed", "Request refused")
    return context


async def current_portal_session(
    context: Annotated[PortalSession | None, Depends(optional_portal_session)],
) -> PortalSession:
    if context is None:
        raise ProblemError(401, "unauthenticated", "Sign in to continue")
    return context


PortalAuth = Annotated[PortalAuthService, Depends(portal_auth_service)]
CurrentCandidate = Annotated[PortalSession, Depends(current_portal_session)]
OptionalCandidate = Annotated[PortalSession | None, Depends(optional_portal_session)]
