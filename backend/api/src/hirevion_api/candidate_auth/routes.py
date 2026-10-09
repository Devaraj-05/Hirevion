"""`/candidate-auth/*` and `/desktop/*`: the desktop app's sign-in, tokens and updates, as
`docs/api/contracts/candidate-auth.md` writes them (SP-07c; ADR-0021)."""

from __future__ import annotations

import hashlib
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from hirevion_api.candidate_auth.deps import (
    Candidate,
    DeviceProof,
    Service,
    app_info,
    dpop_refused,
    refused,
    where,
)
from hirevion_api.candidate_auth.schemas import (
    CandidateBody,
    CandidateInterview,
    LoginBody,
    OrganizationBody,
    OtpRequiredResponse,
    OtpResendBody,
    OtpVerifyBody,
    ProfileResponse,
    RefreshBody,
    RefreshedResponse,
    ReleaseCheckResponse,
    ReleaseLatest,
    SessionInterview,
    SessionTokenResponse,
    SignedInResponse,
)
from hirevion_api.deps import get_db, get_redis
from hirevion_api.ratelimit import enforce, rate_limited
from hirevion_api.routing import api_router
from hirevion_core.candidate_access.dpop import DpopError, RedisReplayCache, check_proof
from hirevion_core.candidate_access.service import (
    InterviewView,
    OtpRequired,
    Profile,
    Refusal,
    SignedIn,
)
from hirevion_core.desktop import releases
from hirevion_core.ratelimit import RateRule

router = api_router(tags=["candidate-auth"])

# Fail closed, like recruiter sign-in: these guard passwords and codes.
LOGIN_BY_IP = RateRule("cand-login-ip", 60, 60, fail_closed=True)
LOGIN_BY_EMAIL = RateRule("cand-login-email", 10, 60, fail_closed=True)
OTP_BY_IP = RateRule("cand-otp-ip", 30, 60, fail_closed=True)
OTP_BY_CHALLENGE = RateRule("cand-otp-challenge", 10, 600, fail_closed=True)
REFRESH_BY_IP = RateRule("cand-refresh-ip", 120, 60, fail_closed=True)
TOKENS_BY_IP = RateRule("cand-token-ip", 120, 60)


def _hashed(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()[:32]


def _interview(view: InterviewView) -> CandidateInterview:
    return CandidateInterview(
        id=view.id,
        job_title=view.job_title,
        status=view.status,  # type: ignore[arg-type]
        starts_at=view.starts_at,
        expires_at=view.expires_at,
        duration_minutes=view.duration_minutes,
        third_eye=view.third_eye,  # type: ignore[arg-type]
        proctoring_level=view.proctoring_level,  # type: ignore[arg-type]
        coding=view.coding,
    )


def _profile_parts(result: SignedIn | Profile) -> dict[str, object]:
    return {
        "candidate": CandidateBody(
            id=result.candidate.id,
            name=result.candidate.name,
            email=result.candidate.email,
            locale=result.candidate.locale,
        ),
        "organization": OrganizationBody(
            id=result.organization.id,
            name=result.organization.name,
            support_email=result.organization.support_email,
        ),
        "interviews": [_interview(view) for view in result.interviews],
    }


def _signed_in(result: SignedIn) -> SignedInResponse:
    return SignedInResponse(
        access_token=result.access_token,
        expires_in=result.expires_in,
        refresh_token=result.refresh_token,
        refresh_expires_in=result.refresh_expires_in,
        **_profile_parts(result),  # type: ignore[arg-type]
    )


@router.post(
    "/candidate-auth/login",
    dependencies=[Depends(rate_limited(LOGIN_BY_IP))],
    responses={200: {"model": SignedInResponse | OtpRequiredResponse}},
)
async def candidate_login(
    body: LoginBody, request: Request, response: Response, proof: DeviceProof, auth: Service
) -> SignedInResponse | OtpRequiredResponse:
    """Signs in with PRD §28's six checks; a new device may first need an emailed code."""
    await enforce(request, response, LOGIN_BY_EMAIL, _hashed(body.email))
    app = app_info(body.app.version, body.app.channel, body.app.os, body.app.arch)
    try:
        result = await auth.login(
            body.email, body.password, app, body.device.name, proof, **where(request)
        )
    except Refusal as refusal:
        raise refused(refusal) from refusal
    if isinstance(result, OtpRequired):
        return OtpRequiredResponse(
            challenge_id=result.challenge_id, sent_to=result.sent_to, expires_in=result.expires_in
        )
    return _signed_in(result)


@router.post("/candidate-auth/otp/verify", dependencies=[Depends(rate_limited(OTP_BY_IP))])
async def verify_candidate_code(
    body: OtpVerifyBody, request: Request, response: Response, proof: DeviceProof, auth: Service
) -> SignedInResponse:
    """Confirms a new device with the emailed code, and signs in."""
    await enforce(request, response, OTP_BY_CHALLENGE, str(body.challenge_id))
    try:
        return _signed_in(
            await auth.verify_code(body.challenge_id, body.code, proof, **where(request))
        )
    except Refusal as refusal:
        raise refused(refusal) from refusal


@router.post(
    "/candidate-auth/otp/resend",
    status_code=202,
    dependencies=[Depends(rate_limited(OTP_BY_IP))],
)
async def resend_candidate_code(
    body: OtpResendBody, request: Request, proof: DeviceProof, auth: Service
) -> None:
    """Emails a new code, at most once a minute."""
    try:
        await auth.resend_code(body.challenge_id, proof, **where(request))
    except Refusal as refusal:
        raise refused(refusal) from refusal


@router.post("/candidate-auth/refresh", dependencies=[Depends(rate_limited(REFRESH_BY_IP))])
async def refresh_candidate_token(
    body: RefreshBody, request: Request, proof: DeviceProof, auth: Service
) -> RefreshedResponse:
    """A new access token and the next refresh token; the one sent is spent."""
    try:
        result = await auth.refresh(body.refresh_token, proof, **where(request))
    except Refusal as refusal:
        raise refused(refusal) from refusal
    return RefreshedResponse(
        access_token=result.access_token,
        expires_in=result.expires_in,
        refresh_token=result.refresh_token,
        refresh_expires_in=result.refresh_expires_in,
    )


@router.post("/candidate-auth/logout", status_code=204)
async def candidate_logout(request: Request, principal: Candidate, auth: Service) -> None:
    """Signs this device out: its refresh family is revoked."""
    await auth.logout(principal.claims, **where(request))


@router.get("/candidate-auth/me")
async def candidate_profile(principal: Candidate, auth: Service) -> ProfileResponse:
    """The candidate, their organisation and the interviews they can take now."""
    profile = await auth.profile(principal.claims)
    return ProfileResponse(**_profile_parts(profile))  # type: ignore[arg-type]


@router.post(
    "/candidate-auth/interviews/{interview_id}/session-token",
    dependencies=[Depends(rate_limited(TOKENS_BY_IP))],
)
async def interview_session_token(
    interview_id: UUID, request: Request, principal: Candidate, auth: Service
) -> SessionTokenResponse:
    """A token for one interview: what the interview, proctoring, recording and third-eye routes
    take."""
    try:
        result = await auth.session_token(principal.claims, interview_id, **where(request))
    except Refusal as refusal:
        raise refused(refusal) from refusal
    return SessionTokenResponse(
        session_token=result.token,
        expires_at=result.expires_at,
        interview=SessionInterview(
            id=result.interview.id,
            status=result.interview.status,  # type: ignore[arg-type]
            starts_at=result.interview.starts_at,
            expires_at=result.interview.expires_at,
            duration_minutes=result.interview.duration_minutes,
        ),
    )


# Desktop releases (public: the app checks before sign-in)


async def _optional_jkt(request: Request) -> str | None:
    """The device key from an optional proof, for staged rollouts; a bad proof is refused."""
    header = request.headers.get("dpop")
    if not header:
        return None
    try:
        proof = await check_proof(
            header,
            method=request.method,
            url=str(request.url.replace(query="", fragment="")),
            replay=RedisReplayCache(get_redis(request)),
        )
    except DpopError as error:
        raise dpop_refused() from error
    return proof.jkt


@router.get("/desktop/releases/check")
async def check_desktop_release(
    request: Request,
    version: Annotated[str, Query(max_length=40)],
    channel: Annotated[str, Query(max_length=20)] = "stable",
    arch: Annotated[str, Query(max_length=20)] = "x64",
) -> ReleaseCheckResponse:
    """Whether this app version may run, and the newest one this device may have."""
    jkt = await _optional_jkt(request)
    async with get_db(request).unscoped() as session:
        result = await releases.check(session, version, channel, arch, jkt)
    latest = result.latest
    return ReleaseCheckResponse(
        status=result.status,
        latest=ReleaseLatest(
            version=latest.version, notes=latest.notes, published_at=latest.published_at
        )
        if latest is not None
        else None,
        minimum_version=result.minimum_version,
        download_url=result.download_url,
    )


@router.get(
    "/desktop/update-manifest/{target}/{arch}/{current_version}",
    responses={204: {"description": "No update applies"}},
)
async def desktop_update_manifest(
    target: str,
    arch: str,
    current_version: str,
    request: Request,
    channel: Annotated[str, Query(max_length=20)] = "stable",
) -> Response:
    """The Tauri v2 updater's manifest: the newest release for this device, never older than
    the running version; 204 when none applies."""
    jkt = await _optional_jkt(request)
    async with get_db(request).unscoped() as session:
        manifest = await releases.update_manifest(
            session, target, arch, current_version, channel=channel, jkt=jkt
        )
    if manifest is None:
        return Response(status_code=204)
    return JSONResponse(manifest)
