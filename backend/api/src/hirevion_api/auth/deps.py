"""The auth service and the session, as route dependencies."""

from __future__ import annotations

import hmac
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request

from hirevion_api.auth.cookies import CSRF_COOKIE, SESSION_COOKIE
from hirevion_api.auth.csrf import SAFE_METHODS
from hirevion_api.deps import get_db, get_redis
from hirevion_api.problems import ProblemError
from hirevion_core.identity.service import AuthService
from hirevion_core.identity.sessions import SessionContext, hash_token, resolve_session


def auth_service(request: Request) -> AuthService:
    state = request.app.state
    return AuthService(
        get_db(request), get_redis(request), policy=state.password_policy, settings=state.identity
    )


async def optional_session(request: Request) -> SessionContext | None:
    """The live session from the cookie, or None. On a state-changing request the CSRF cookie
    must also belong to this session (the middleware has checked it matches the header)."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    context = await resolve_session(
        get_db(request), token, settings=request.app.state.identity, now=datetime.now(UTC)
    )
    if context is None:
        return None
    if request.method not in SAFE_METHODS:
        csrf = request.cookies.get(CSRF_COOKIE, "")
        if not hmac.compare_digest(hash_token(csrf), context.csrf_hash):
            raise ProblemError(403, "csrf-failed", "Request refused")
    return context


async def current_session(
    context: Annotated[SessionContext | None, Depends(optional_session)],
) -> SessionContext:
    if context is None:
        raise ProblemError(401, "unauthenticated", "Sign in to continue")
    return context


Auth = Annotated[AuthService, Depends(auth_service)]
CurrentSession = Annotated[SessionContext, Depends(current_session)]
OptionalSession = Annotated[SessionContext | None, Depends(optional_session)]
