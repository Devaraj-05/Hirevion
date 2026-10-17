"""The third eye's routes, as `docs/api/contracts/third-eye.md` writes them (SP-13).

- The desktop's (`/third-eye/pairings*`) carry the interview-session token with a fresh DPoP
  proof (ADR-0021); the token names the interview and the candidate the pairing is bound to.
- The phone's (`/third-eye/redeem`, `/third-eye/rejoin`) take no account: the pairing token,
  then the device secret, is the credential. Both are limited per address.
"""

from __future__ import annotations

from typing import cast
from uuid import UUID

from fastapi import Depends, Request, Response

from hirevion_api.candidate_auth.deps import AnyInterviewSession, CandidatePrincipal, where
from hirevion_api.deps import client_ip, get_db, get_redis
from hirevion_api.interview_session.routes import media
from hirevion_api.problems import ProblemError
from hirevion_api.ratelimit import enforce, rate_limited
from hirevion_api.routing import api_router
from hirevion_api.third_eye.schemas import (
    DeviceInfo,
    InterviewNames,
    IssueBody,
    JoinResponse,
    PairingIssued,
    PairingState,
    Placement,
    RedeemBody,
    RejoinBody,
    VideoInfo,
)
from hirevion_core.interview_session.conductor import MediaUnavailable
from hirevion_core.interviews.lifecycle import By
from hirevion_core.ratelimit import RateRule
from hirevion_core.third_eye.egress import EgressRecorder, build_output
from hirevion_core.third_eye.service import Joined, PairingView, ThirdEye
from hirevion_core.third_eye.settings import ThirdEyeSettings, load_third_eye_settings

router = api_router(tags=["third-eye"])

# A desktop asks for a pairing when the candidate shows the QR code; a few retries a minute is
# plenty, and polling the status every 2 s is twice that.
ISSUES_BY_INTERVIEW = RateRule("eye-issue", 20, 60)
STATUS_BY_INTERVIEW = RateRule("eye-status", 120, 60)
# A phone redeems once and rejoins after a lock; guessing a 256-bit token isn't feasible, but
# an address hammering the route is refused anyway.
PHONE_BY_IP = RateRule("eye-phone", 30, 60)
DESKTOP_BY_IP = RateRule("eye-desktop-ip", 600, 60)


def settings(request: Request) -> ThirdEyeSettings:
    found = getattr(request.app.state, "third_eye_settings", None)
    if found is None:
        found = load_third_eye_settings()
        request.app.state.third_eye_settings = found
    return cast(ThirdEyeSettings, found)


def third_eye(request: Request) -> ThirdEye:
    control = media(request)
    resolved = settings(request)
    recorder = None
    output = build_output(resolved, getattr(request.app.state, "storage", None))
    if control is not None and output is not None:
        recorder = EgressRecorder(get_db(request), get_redis(request), control, output)
    return ThirdEye(get_db(request), get_redis(request), control, resolved, recorder=recorder)


def _token_interview(principal: CandidatePrincipal) -> UUID:
    interview_id = principal.claims.interview_id
    if interview_id is None:
        raise ProblemError(401, "token-invalid", "Sign in to continue")
    return interview_id


def _by(request: Request, principal: CandidatePrincipal) -> By:
    place = where(request)
    return By("candidate", str(principal.account_id), place["ip"], place["user_agent"])


def _unavailable(error: Exception) -> ProblemError:
    return ProblemError(503, "media-unavailable", "The camera service isn't available; try again")


def _state(item: PairingView) -> PairingState:
    return PairingState(
        pairing_id=item.pairing_id,
        status=item.status,  # type: ignore[arg-type]
        expires_at=item.expires_at,
        device=DeviceInfo(**item.device) if item.device else None,
        connected_at=item.connected_at,
        last_seen_at=item.last_seen_at,
        video=VideoInfo(**item.video) if item.video else None,
        reconnects=item.reconnects,
    )


def _joined(joined: Joined) -> JoinResponse:
    return JoinResponse(
        pairing_id=joined.pairing_id,
        livekit_url=joined.livekit_url,
        participant_token=joined.participant.token,
        participant_identity=joined.participant.identity,
        expires_at=joined.participant.expires_at,
        device_token=joined.device_token,
        interview=InterviewNames(company=joined.company, job_title=joined.job_title),
        placement=Placement(**joined.placement),
    )


# The desktop.


@router.post(
    "/third-eye/pairings",
    status_code=201,
    dependencies=[Depends(rate_limited(DESKTOP_BY_IP))],
)
async def issue_pairing(
    body: IssueBody, request: Request, response: Response, principal: AnyInterviewSession
) -> PairingIssued:
    """A pairing for the interview's phone: show `qr_url` as a QR code. Issuing again revokes
    the previous pairing and disconnects its phone."""
    if body.interview_id != _token_interview(principal):
        raise ProblemError(403, "wrong-interview", "This token is for another interview")
    await enforce(request, response, ISSUES_BY_INTERVIEW, str(body.interview_id))
    try:
        issued = await third_eye(request).issue(
            principal.organization_id,
            body.interview_id,
            account_id=principal.account_id,
            by=_by(request, principal),
        )
    except MediaUnavailable as error:
        raise _unavailable(error) from error
    return PairingIssued(
        pairing_id=issued.pairing.pairing_id,
        qr_url=issued.qr_url,
        expires_at=issued.pairing.expires_at,
        status=issued.pairing.status,  # type: ignore[arg-type]
    )


@router.get("/third-eye/pairings/{pairing_id}", dependencies=[Depends(rate_limited(DESKTOP_BY_IP))])
async def pairing_status(
    pairing_id: UUID, request: Request, response: Response, principal: AnyInterviewSession
) -> PairingState:
    """The pairing as LiveKit shows it; the desktop polls it every 2 s while pairing."""
    interview_id = _token_interview(principal)
    await enforce(request, response, STATUS_BY_INTERVIEW, str(interview_id))
    found = await third_eye(request).status(principal.organization_id, interview_id, pairing_id)
    return _state(found)


@router.post(
    "/third-eye/pairings/{pairing_id}/revoke",
    status_code=204,
    dependencies=[Depends(rate_limited(DESKTOP_BY_IP))],
)
async def revoke_pairing(
    pairing_id: UUID, request: Request, principal: AnyInterviewSession
) -> None:
    """Ends the pairing and disconnects its phone."""
    await third_eye(request).revoke(
        principal.organization_id,
        _token_interview(principal),
        pairing_id,
        by=_by(request, principal),
    )


# The phone.


@router.post("/third-eye/redeem", dependencies=[Depends(rate_limited(PHONE_BY_IP))])
async def redeem_pairing(body: RedeemBody, request: Request) -> JoinResponse:
    """Spends the QR code's token (once, within two minutes) for a camera-only LiveKit token and
    a device secret for rejoining."""
    try:
        joined = await third_eye(request).redeem(
            body.token, user_agent=body.device.user_agent, ip=client_ip(request)
        )
    except MediaUnavailable as error:
        raise _unavailable(error) from error
    return _joined(joined)


@router.post("/third-eye/rejoin", dependencies=[Depends(rate_limited(PHONE_BY_IP))])
async def rejoin_pairing(body: RejoinBody, request: Request) -> JoinResponse:
    """A fresh LiveKit token for a phone that redeemed, after its token ran out while locked."""
    try:
        joined = await third_eye(request).rejoin(body.device_token)
    except MediaUnavailable as error:
        raise _unavailable(error) from error
    return _joined(joined)
