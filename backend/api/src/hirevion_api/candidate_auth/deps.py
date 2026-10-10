"""DPoP and candidate-token dependencies for the desktop's routes (ADR-0021).

Desktop routes never take a cookie: each request proves the device key (`DPoP`), and those past
sign-in carry `Authorization: DPoP <token>` bound to that key. A token's sign-in must still be
live (not signed out of, not revoked for reuse), so refusals take effect at once.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, cast
from uuid import UUID

from fastapi import Depends, Request

from hirevion_api.deps import client_ip, get_db, get_redis
from hirevion_api.problems import ProblemError
from hirevion_core.candidate_access.dpop import DpopError, Proof, RedisReplayCache, check_proof
from hirevion_core.candidate_access.service import AppInfo, CandidateAuthService, Refusal
from hirevion_core.candidate_access.tokens import (
    CandidateAuthSettings,
    Scope,
    TokenClaims,
    TokenError,
    TokenSigner,
)

_DPOP_REFUSED = {"WWW-Authenticate": 'DPoP error="invalid_dpop_proof", algs="ES256"'}
_TOKEN_REFUSED = {"WWW-Authenticate": 'DPoP error="invalid_token", algs="ES256"'}


def signer(request: Request) -> TokenSigner:
    return cast(TokenSigner, request.app.state.candidate_signer)


def candidate_auth(request: Request) -> CandidateAuthService:
    state = request.app.state
    settings: CandidateAuthSettings = state.candidate_auth
    return CandidateAuthService(
        get_db(request),
        get_redis(request),
        signer(request),
        settings=settings,
        identity=state.identity,
    )


def refused(refusal: Refusal) -> ProblemError:
    return ProblemError(
        refusal.status, refusal.code, refusal.title, headers=refusal.headers, **refusal.extra
    )


def dpop_refused() -> ProblemError:
    return ProblemError(401, "dpop-invalid", "Request refused", headers=_DPOP_REFUSED)


def where(request: Request) -> dict[str, str | None]:
    return {"ip": client_ip(request), "user_agent": request.headers.get("user-agent")}


def _url(request: Request) -> str:
    return str(request.url.replace(query="", fragment=""))


async def _proof(
    request: Request, *, access_token: str | None = None, expected_jkt: str | None = None
) -> Proof:
    header = request.headers.get("dpop")
    if not header:
        raise dpop_refused()
    try:
        return await check_proof(
            header,
            method=request.method,
            url=_url(request),
            replay=RedisReplayCache(get_redis(request)),
            access_token=access_token,
            expected_jkt=expected_jkt,
        )
    except DpopError as error:
        raise dpop_refused() from error


async def device_proof(request: Request) -> Proof:
    """The proof on a request before sign-in (login, codes, refresh): it names the device key."""
    return await _proof(request)


@dataclass(frozen=True, slots=True)
class CandidatePrincipal:
    claims: TokenClaims
    proof: Proof

    @property
    def account_id(self) -> UUID:
        return self.claims.account_id

    @property
    def organization_id(self) -> UUID:
        return self.claims.organization_id


async def _principal(request: Request, scope: Scope) -> CandidatePrincipal:
    authorization = request.headers.get("authorization", "")
    kind, _, token = authorization.partition(" ")
    if kind.lower() != "dpop" or not token:
        raise ProblemError(401, "token-invalid", "Sign in to continue", headers=_TOKEN_REFUSED)
    try:
        claims = signer(request).verify(token.strip(), scope=scope)
    except TokenError as error:
        raise ProblemError(
            401, "token-invalid", "Sign in to continue", headers=_TOKEN_REFUSED
        ) from error
    proof = await _proof(request, access_token=token.strip(), expected_jkt=claims.jkt)
    if not await candidate_auth(request).family_active(claims):
        raise ProblemError(401, "token-invalid", "Sign in to continue", headers=_TOKEN_REFUSED)
    return CandidatePrincipal(claims, proof)


async def candidate_principal(request: Request) -> CandidatePrincipal:
    """An access token (`scope` `candidate`) with its proof."""
    return await _principal(request, "candidate")


async def interview_principal(request: Request, interview_id: UUID) -> CandidatePrincipal:
    """An interview-session token for the interview in the path, with its proof."""
    principal = await _principal(request, "interview")
    if principal.claims.interview_id != interview_id:
        raise ProblemError(403, "wrong-interview", "This token is for another interview")
    return principal


async def session_principal(request: Request) -> CandidatePrincipal:
    """An interview-session token with its proof, for routes whose path doesn't name the
    interview (a recording segment's body or id does); the route compares it with the token's."""
    return await _principal(request, "interview")


def app_info(version: str, channel: str, os: str, arch: str) -> AppInfo:
    return AppInfo(version=version, channel=channel, os=os, arch=arch)


DeviceProof = Annotated[Proof, Depends(device_proof)]
Candidate = Annotated[CandidatePrincipal, Depends(candidate_principal)]
InterviewSession = Annotated[CandidatePrincipal, Depends(interview_principal)]
AnyInterviewSession = Annotated[CandidatePrincipal, Depends(session_principal)]
Service = Annotated[CandidateAuthService, Depends(candidate_auth)]
