"""`/api/v1/auth/*`: sign-in, sessions, passwords and email (SP-02 spec, ADR-0013).

Answers that could reveal whether an account exists are identical: a wrong password and an
unknown email (401 `invalid-credentials`), and `password/forgot` (always 202).
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from uuid import UUID

from fastapi import Depends, Request, Response

from hirevion_api.auth.cookies import clear_session_cookies, set_session_cookies
from hirevion_api.auth.deps import Auth, CurrentSession, OptionalSession
from hirevion_api.auth.schemas import (
    EmailChangeRequest,
    EmailVerifyRequest,
    ForgotPasswordRequest,
    LoginRequest,
    PasswordChangeRequest,
    SessionItem,
    SessionOrganization,
    SessionResponse,
    SessionUser,
    TokenPasswordRequest,
)
from hirevion_api.deps import client_ip
from hirevion_api.problems import ProblemError
from hirevion_api.ratelimit import enforce, rate_limited
from hirevion_api.routing import api_router
from hirevion_core.identity.service import LoginRefused, PasswordOutcome
from hirevion_core.ratelimit import RateRule

router = api_router(tags=["auth"])

# Sign-in and token routes refuse requests when Valkey is down (fail closed).
# Per IP it allows for an office behind one address; per email, the lockout does the rest.
LOGIN_BY_IP = RateRule("login-ip", 30, 60, fail_closed=True)
LOGIN_BY_EMAIL = RateRule("login-email", 10, 60, fail_closed=True)
FORGOT_BY_IP = RateRule("forgot-ip", 20, 3600, fail_closed=True)
FORGOT_BY_EMAIL = RateRule("forgot-email", 5, 3600, fail_closed=True)
TOKENS_BY_IP = RateRule("auth-token-ip", 20, 60, fail_closed=True)

_INVALID_CREDENTIALS = ("invalid-credentials", "Email or password is incorrect")
_INVALID_TOKEN = (
    "invalid-token",
    "This link has expired or was already used",
    "Ask for a new link.",
)


def _email_subject(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()[:32]


def _where(request: Request) -> dict[str, str | None]:
    return {"ip": client_ip(request), "user_agent": request.headers.get("user-agent")}


def _rejected(outcomes: Sequence[str], field: str) -> ProblemError:
    """422 with each reason on the field it concerns, for the form to show."""
    pointers = {"wrong_current": "#/current_password", "wrong_password": "#/password"}
    errors = [
        {"detail": outcome, "pointer": pointers.get(outcome, f"#/{field}")} for outcome in outcomes
    ]
    return ProblemError(422, "password-rejected", "The password wasn't accepted", errors=errors)


@router.post("/auth/login", status_code=204, dependencies=[Depends(rate_limited(LOGIN_BY_IP))])
async def login(body: LoginRequest, request: Request, response: Response, auth: Auth) -> None:
    """Signs in: sets the session and CSRF cookies."""
    await enforce(request, response, LOGIN_BY_EMAIL, _email_subject(body.email))
    result = await auth.login(body.email, body.password, **_where(request))
    if isinstance(result, LoginRefused):
        if result.retry_after is not None:
            minutes = math.ceil(result.retry_after / 60)
            raise ProblemError(
                429,
                "rate-limited",
                "Too many attempts",
                f"Try again in {minutes} minute{'s' if minutes != 1 else ''}.",
                headers={"Retry-After": str(result.retry_after)},
                retry_after=result.retry_after,
            )
        raise ProblemError(401, *_INVALID_CREDENTIALS)
    set_session_cookies(response, result.session_token, result.csrf_token)


@router.post("/auth/logout", status_code=204)
async def logout(
    request: Request, response: Response, auth: Auth, context: OptionalSession
) -> None:
    """Signs out this browser. Answers 204 even without a session, and clears the cookies."""
    if context is not None:
        await auth.logout(context, **_where(request))
    clear_session_cookies(response)


@router.get("/auth/session")
async def get_session(auth: Auth, context: CurrentSession) -> SessionResponse:
    """Who is signed in, their organisation, roles and permissions (401 when nobody is)."""
    view = await auth.session_view(context)
    return SessionResponse(
        user=SessionUser(id=view.user.id, name=view.user.name, email=view.user.email),
        organization=SessionOrganization(id=view.organization.id, name=view.organization.name)
        if view.organization is not None
        else None,
        roles=view.roles,
        permissions=view.permissions,
    )


@router.get("/auth/sessions")
async def list_sessions(auth: Auth, context: CurrentSession) -> list[SessionItem]:
    """The signed-in user's sessions, most recently active first."""
    return [
        SessionItem(
            id=item.id,
            created_at=item.created_at,
            last_seen_at=item.last_seen_at,
            ip=item.ip,
            user_agent=item.user_agent,
            current=item.current,
        )
        for item in await auth.list_sessions(context)
    ]


@router.delete("/auth/sessions/{session_id}", status_code=204)
async def revoke_session(
    session_id: UUID, request: Request, auth: Auth, context: CurrentSession
) -> None:
    """Signs out one of the user's other sessions."""
    if not await auth.revoke_session(context, session_id, **_where(request)):
        raise ProblemError(404, "not-found", "No such session")


@router.post("/auth/sessions/revoke-others", status_code=204)
async def revoke_other_sessions(request: Request, auth: Auth, context: CurrentSession) -> None:
    """Signs out everywhere except this browser."""
    await auth.revoke_other_sessions(context, **_where(request))


@router.post("/auth/password/change", status_code=204)
async def change_password(
    body: PasswordChangeRequest, request: Request, auth: Auth, context: CurrentSession
) -> None:
    """Changes the password; the user's other sessions end."""
    outcome = await auth.change_password(
        context, body.current_password, body.new_password, **_where(request)
    )
    if outcome:
        raise _rejected(outcome, "new_password")


@router.post(
    "/auth/password/forgot",
    status_code=202,
    response_class=Response,
    dependencies=[Depends(rate_limited(FORGOT_BY_IP))],
)
async def forgot_password(
    body: ForgotPasswordRequest, request: Request, response: Response, auth: Auth
) -> Response:
    """Emails a reset link if the account exists. The answer is the same either way."""
    await enforce(request, response, FORGOT_BY_EMAIL, _email_subject(body.email))
    await auth.request_reset(body.email, **_where(request))
    return Response(status_code=202, headers=dict(response.headers))


@router.post(
    "/auth/password/reset", status_code=204, dependencies=[Depends(rate_limited(TOKENS_BY_IP))]
)
async def reset_password(body: TokenPasswordRequest, request: Request, auth: Auth) -> None:
    """Sets a new password from an emailed link; every session ends."""
    _raise_for(await auth.reset_password(body.token, body.password, **_where(request)))


@router.post(
    "/auth/password/set", status_code=204, dependencies=[Depends(rate_limited(TOKENS_BY_IP))]
)
async def set_password(body: TokenPasswordRequest, request: Request, auth: Auth) -> None:
    """Sets an invited user's first password, which activates the account."""
    _raise_for(await auth.set_password(body.token, body.password, **_where(request)))


def _raise_for(outcome: Sequence[PasswordOutcome] | None) -> None:
    if not outcome:
        return
    if "invalid_token" in outcome:
        raise ProblemError(400, *_INVALID_TOKEN)
    raise _rejected(outcome, "password")


@router.post("/auth/email/change", status_code=202, response_class=Response)
async def change_email(
    body: EmailChangeRequest, request: Request, auth: Auth, context: CurrentSession
) -> Response:
    """Sends a confirmation link to the new address. An address already in use gets the same
    answer, and nothing is sent."""
    outcome = await auth.request_email_change(
        context, body.new_email, body.password, **_where(request)
    )
    if outcome == "wrong_password":
        raise _rejected(["wrong_password"], "password")
    return Response(status_code=202)


@router.post(
    "/auth/email/verify", status_code=204, dependencies=[Depends(rate_limited(TOKENS_BY_IP))]
)
async def verify_email(body: EmailVerifyRequest, request: Request, auth: Auth) -> None:
    """Confirms a new email address from its emailed link."""
    if not await auth.verify_email(body.token, **_where(request)):
        raise ProblemError(400, *_INVALID_TOKEN)
