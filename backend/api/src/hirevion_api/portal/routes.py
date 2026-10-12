"""`/api/v1/portal/*`: the candidate portal (master plan §6.3; ADR-0022).

Sign-in, sign-out, the invitation's set-password link and resets set and clear the candidate's
own cookies; answers that could reveal whether an account exists are identical, as on the
recruiter side (ADR-0013). The candidate's interviews and requests need a portal session; the
notices and the download page are public, because the invitation links to them.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request, Response

from hirevion_api.auth.schemas import ForgotPasswordRequest, LoginRequest, TokenPasswordRequest
from hirevion_api.deps import client_ip, get_db
from hirevion_api.idempotency import Idempotency, idempotency
from hirevion_api.portal.cookies import clear_portal_cookies, set_portal_cookies
from hirevion_api.portal.deps import CurrentCandidate, OptionalCandidate, PortalAuth
from hirevion_api.portal.schemas import (
    DownloadRelease,
    DownloadsResponse,
    NoticesResponse,
    PolicyItem,
    PortalAccount,
    PortalInterviewItem,
    PortalInterviewList,
    PortalOrganization,
    PortalRequestCreate,
    PortalRequestItem,
    PortalSessionResponse,
)
from hirevion_api.problems import ProblemError
from hirevion_api.ratelimit import enforce, rate_limited
from hirevion_api.routing import api_router
from hirevion_core.candidate_portal import notices, requests
from hirevion_core.candidate_portal.interviews import portal_interviews
from hirevion_core.candidate_portal.requests import NewRequest
from hirevion_core.desktop import releases
from hirevion_core.identity.service import LoginRefused, PasswordOutcome
from hirevion_core.interviews.invitations import SYSTEM_REQUIREMENTS, THIRD_EYE_REQUIREMENT
from hirevion_core.models import CandidateAccount, CandidateRequest
from hirevion_core.models.desktop_release import DESKTOP_ARCHES
from hirevion_core.ratelimit import RateRule

router = api_router(tags=["portal"])

# The recruiter side's limits (ADR-0013), counted apart from it. Fail closed.
LOGIN_BY_IP = RateRule("portal-login-ip", 60, 60, fail_closed=True)
LOGIN_BY_EMAIL = RateRule("portal-login-email", 10, 60, fail_closed=True)
FORGOT_BY_IP = RateRule("portal-forgot-ip", 20, 3600, fail_closed=True)
FORGOT_BY_EMAIL = RateRule("portal-forgot-email", 5, 3600, fail_closed=True)
TOKENS_BY_IP = RateRule("portal-token-ip", 20, 60, fail_closed=True)
# Each request is mailed and lands with a recruiter: a person asks a handful, not hundreds.
REQUESTS_BY_ACCOUNT = RateRule("portal-requests-account", 20, 3600, fail_closed=True)

_INVALID_CREDENTIALS = ("invalid-credentials", "Email or password is incorrect")
_INVALID_TOKEN = (
    "invalid-token",
    "This link has expired or was already used",
    "Ask for a new link.",
)

Idempotent = Annotated[Idempotency, Depends(idempotency)]


def _email_subject(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()[:32]


def _where(request: Request) -> dict[str, str | None]:
    return {"ip": client_ip(request), "user_agent": request.headers.get("user-agent")}


def _locked(refused: LoginRefused) -> ProblemError:
    retry_after = refused.retry_after or 1
    minutes = math.ceil(retry_after / 60)
    return ProblemError(
        429,
        "rate-limited",
        "Too many attempts",
        f"Try again in {minutes} minute{'s' if minutes != 1 else ''}.",
        headers={"Retry-After": str(retry_after)},
        retry_after=retry_after,
    )


def _raise_for(outcome: Sequence[PasswordOutcome] | None) -> None:
    if not outcome:
        return
    if "invalid_token" in outcome:
        raise ProblemError(400, *_INVALID_TOKEN)
    errors = [{"detail": item, "pointer": "#/password"} for item in outcome]
    raise ProblemError(422, "password-rejected", "The password wasn't accepted", errors=errors)


# Sign-in, sign-out and passwords


@router.post(
    "/portal/auth/login", status_code=204, dependencies=[Depends(rate_limited(LOGIN_BY_IP))]
)
async def portal_login(
    body: LoginRequest, request: Request, response: Response, auth: PortalAuth
) -> None:
    """Signs a candidate in to the portal: sets the candidate's session and CSRF cookies."""
    await enforce(request, response, LOGIN_BY_EMAIL, _email_subject(body.email))
    result = await auth.login(body.email, body.password, **_where(request))
    if isinstance(result, LoginRefused):
        if result.retry_after is not None:
            raise _locked(result)
        raise ProblemError(401, *_INVALID_CREDENTIALS)
    set_portal_cookies(response, result.session_token, result.csrf_token)


@router.post("/portal/auth/logout", status_code=204)
async def portal_logout(
    request: Request, response: Response, auth: PortalAuth, context: OptionalCandidate
) -> None:
    """Signs out of the portal. Answers 204 even without a session, and clears the cookies."""
    if context is not None:
        await auth.logout(context, **_where(request))
    clear_portal_cookies(response)


@router.get("/portal/auth/session")
async def get_portal_session(auth: PortalAuth, context: CurrentCandidate) -> PortalSessionResponse:
    """Who is signed in to the portal (401 when nobody is)."""
    view = await auth.view(context)
    return PortalSessionResponse(
        account=PortalAccount(
            id=view.account_id, name=view.name, email=view.email, locale=view.locale
        ),
        organization=PortalOrganization(
            id=view.organization_id, name=view.organization_name, support_email=view.support_email
        ),
    )


@router.post(
    "/portal/auth/password/set",
    status_code=204,
    dependencies=[Depends(rate_limited(TOKENS_BY_IP))],
)
async def portal_set_password(
    body: TokenPasswordRequest, request: Request, auth: PortalAuth
) -> None:
    """The invitation's link: sets the first password, activates the account and confirms the
    email address."""
    _raise_for(await auth.set_password(body.token, body.password, **_where(request)))


@router.post(
    "/portal/auth/password/forgot",
    status_code=202,
    response_class=Response,
    dependencies=[Depends(rate_limited(FORGOT_BY_IP))],
)
async def portal_forgot_password(
    body: ForgotPasswordRequest, request: Request, response: Response, auth: PortalAuth
) -> Response:
    """Emails a reset link (or, before the first password, a fresh invitation link) if the
    account exists. The answer is the same either way."""
    await enforce(request, response, FORGOT_BY_EMAIL, _email_subject(body.email))
    await auth.request_reset(body.email, **_where(request))
    return Response(status_code=202, headers=dict(response.headers))


@router.post(
    "/portal/auth/password/reset",
    status_code=204,
    dependencies=[Depends(rate_limited(TOKENS_BY_IP))],
)
async def portal_reset_password(
    body: TokenPasswordRequest, request: Request, auth: PortalAuth
) -> None:
    """Sets a new password from an emailed link; every portal session and desktop sign-in
    ends."""
    _raise_for(await auth.reset_password(body.token, body.password, **_where(request)))


# The candidate's interviews and requests


@router.get("/portal/interviews")
async def list_portal_interviews(
    request: Request, context: CurrentCandidate
) -> PortalInterviewList:
    """The interviews the candidate was invited to, soonest window first."""
    now = datetime.now(UTC)
    async with get_db(request).tenant(context.organization_id) as session:
        account = await session.get_one(CandidateAccount, context.account_id)
        items = await portal_interviews(session, account, now)
    return PortalInterviewList(
        now=now,
        interviews=[
            PortalInterviewItem(
                id=item.id,
                reference=item.reference,
                job_title=item.job_title,
                status=item.status,
                starts_at=item.starts_at,
                expires_at=item.expires_at,
                timezone=item.timezone,
                duration_minutes=item.duration_minutes,
                can_take=item.can_take,
                third_eye=item.third_eye,
                recorded=item.recorded,
            )
            for item in items
        ],
    )


def _request_item(row: CandidateRequest) -> PortalRequestItem:
    return PortalRequestItem(
        id=row.id,
        reference=requests.reference(row.id),
        kind=row.kind,  # type: ignore[arg-type]
        status=row.status,  # type: ignore[arg-type]
        message=row.message,
        interview_id=row.interview_id,
        details=row.details,
        response=row.response,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/portal/requests")
async def list_portal_requests(
    request: Request, context: CurrentCandidate
) -> list[PortalRequestItem]:
    """The candidate's own requests, newest first, with the organisation's replies."""
    async with get_db(request).tenant(context.organization_id) as session:
        rows = await requests.list_own(session, context.account_id)
        return [_request_item(row) for row in rows]


@router.post("/portal/requests", status_code=201)
async def create_portal_request(
    body: PortalRequestCreate,
    request: Request,
    response: Response,
    context: CurrentCandidate,
    idem: Idempotent,
) -> PortalRequestItem:
    """Asks the organisation for something (master plan §6.3): it's stored, audited, mailed
    back as an acknowledgement and listed for its recruiters."""
    await enforce(request, response, REQUESTS_BY_ACCOUNT, str(context.account_id))
    async with get_db(request).tenant(context.organization_id) as session:

        async def create() -> PortalRequestItem:
            account = await session.get_one(CandidateAccount, context.account_id)
            row = await requests.create_request(
                session,
                account,
                NewRequest(
                    kind=body.kind,
                    message=body.message,
                    interview_id=body.interview_id,
                    details=body.details,
                ),
                settings=request.app.state.identity,
                **_where(request),
            )
            await session.refresh(row)
            return _request_item(row)

        return await idem.run(
            session, context.organization_id, f"candidate:{context.account_id}", create
        )


# Public pages: the notices and the download


@router.get("/portal/notices")
async def get_portal_notices() -> NoticesResponse:
    """PRD §83: the ten kinds of data an interview may collect, and the six policies."""
    return NoticesResponse(
        disclosures=list(notices.DISCLOSURES),
        policies=[
            PolicyItem(key=policy.key, title=policy.title, body=policy.body)
            for policy in notices.current_policies()
        ],
    )


@router.get("/portal/downloads")
async def get_portal_downloads(request: Request) -> DownloadsResponse:
    """The desktop app's download (SP-07c's registry): the stable channel's page, its newest
    fully rolled-out release per architecture, and the system requirements."""
    async with get_db(request).unscoped() as session:
        channel = await releases.get_channel(session, "stable")
        latest = [
            await releases.latest_release(session, "stable", arch, None) for arch in DESKTOP_ARCHES
        ]
    return DownloadsResponse(
        download_url=channel.download_url,
        minimum_version=channel.minimum_version,
        releases=[
            DownloadRelease(
                arch=release.arch,
                version=release.version,
                notes=release.notes,
                published_at=release.published_at,
            )
            for release in latest
            if release is not None
        ],
        system_requirements=[*SYSTEM_REQUIREMENTS, f"{THIRD_EYE_REQUIREMENT} (if asked)"],
    )
