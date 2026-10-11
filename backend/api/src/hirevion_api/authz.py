"""Who may call what (PRD §81, master plan §9; ADR-0014).

Every route under /api/v1 either declares the permissions it needs with `requires(...)` or is
listed in `UNGUARDED` with a reason. The authorisation-matrix test holds both rules: it fails for
a route that is neither, and calls every guarded route as every system role.

A guard checks the permission first, then, for sensitive changes, that the session confirmed its
password recently (step-up). Permissions are read from the database on every request, so a change
to someone's roles applies at once.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, FastAPI, Request
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, iter_route_contexts

from hirevion_api.auth.deps import CurrentSession
from hirevion_api.deps import client_ip, get_db
from hirevion_api.problems import ProblemError
from hirevion_api.routing import API_PREFIX
from hirevion_core.access.actor import Actor
from hirevion_core.identity.grants import load_grants
from hirevion_core.identity.permissions import PERMISSIONS
from hirevion_core.identity.sessions import SessionContext, is_stepped_up
from hirevion_core.identity.settings import IdentitySettings

# Routes that need no permission: "public" ones need no session at all, and "self" ones act only
# on the signed-in user's own account. The desktop app's routes take no recruiter session at all:
# "device" ones need a DPoP proof of the device key (ADR-0021), "candidate" ones a candidate's
# DPoP-bound access token, "interview" ones an interview-session token for the path's interview.
# "webhook" ones are called by another service and verify its signature over the body.
# Everything else must use `requires(...)`.
UNGUARDED: dict[str, str] = {
    "GET /api/v1/health/live": "public",
    "GET /api/v1/health/ready": "public",
    "GET /api/v1/time": "public",
    "POST /api/v1/auth/login": "public",
    "POST /api/v1/auth/password/forgot": "public",
    "POST /api/v1/auth/password/reset": "public",
    "POST /api/v1/auth/password/set": "public",
    "POST /api/v1/auth/email/verify": "public",
    "POST /api/v1/auth/logout": "self",
    "GET /api/v1/auth/session": "self",
    "GET /api/v1/auth/sessions": "self",
    "DELETE /api/v1/auth/sessions/{session_id}": "self",
    "POST /api/v1/auth/sessions/revoke-others": "self",
    "POST /api/v1/auth/password/change": "self",
    "POST /api/v1/auth/step-up": "self",
    "POST /api/v1/auth/email/change": "self",
    "POST /api/v1/candidate-auth/login": "device",
    "POST /api/v1/candidate-auth/otp/verify": "device",
    "POST /api/v1/candidate-auth/otp/resend": "device",
    "POST /api/v1/candidate-auth/refresh": "device",
    "POST /api/v1/candidate-auth/logout": "candidate",
    "GET /api/v1/candidate-auth/me": "candidate",
    "POST /api/v1/candidate-auth/interviews/{interview_id}/session-token": "candidate",
    "GET /api/v1/interviews/{interview_id}/briefing": "interview",
    "POST /api/v1/interviews/{interview_id}/system-checks": "interview",
    "POST /api/v1/interviews/{interview_id}/consents": "interview",
    "POST /api/v1/interviews/{interview_id}/accommodations": "interview",
    "POST /api/v1/interviews/{interview_id}/start": "interview",
    "GET /api/v1/interviews/{interview_id}/session": "interview",
    "POST /api/v1/interviews/{interview_id}/answer": "interview",
    "POST /api/v1/interviews/{interview_id}/workspace": "interview",
    "POST /api/v1/interviews/{interview_id}/complete": "interview",
    "POST /api/v1/recordings/segments": "interview",
    "POST /api/v1/recordings/segments/{segment_id}/ack": "interview",
    "GET /api/v1/recordings/interviews/{interview_id}/segments": "interview",
    "POST /api/v1/livekit/webhook": "webhook",
    "GET /api/v1/desktop/releases/check": "public",
    "GET /api/v1/desktop/update-manifest/{target}/{arch}/{current_version}": "public",
}


@dataclass(frozen=True, slots=True)
class Principal:
    """The signed-in user, with what they may do."""

    context: SessionContext
    permissions: frozenset[str]
    role_keys: frozenset[str]

    @property
    def user_id(self) -> UUID:
        return self.context.user_id

    @property
    def organization_id(self) -> UUID:
        return self.context.organization_id

    @property
    def reviewer_only(self) -> UUID | None:
        """Interviews are scoped to this user's own reviews unless they may view candidates:
        None means every interview in scope, else only those this user reviews."""
        return None if "candidates.view" in self.permissions else self.user_id

    def actor(self, request: Request) -> Actor:
        """The principal as the access domain's acting user, with where the request came from."""
        return Actor(
            self.user_id,
            self.organization_id,
            self.permissions,
            ip=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )


async def current_principal(request: Request, context: CurrentSession) -> Principal:
    """The session's principal; FastAPI resolves it once per request."""
    async with get_db(request).tenant(context.organization_id) as session:
        grants = await load_grants(session, context.user_id)
    return Principal(context, frozenset(grants.permissions), frozenset(grants.role_keys))


class Requires:
    """A route guard: the principal needs any one of `permissions` and, with `step_up`, a
    password confirmed within `HV_STEP_UP_MINUTES`."""

    def __init__(self, *permissions: str, step_up: bool = False) -> None:
        if not permissions:
            raise ValueError("a guard needs at least one permission")
        unknown = [p for p in permissions if p not in PERMISSIONS]
        if unknown:
            raise ValueError(f"unknown permissions: {', '.join(unknown)}")
        self.permissions = permissions
        self.step_up = step_up

    async def __call__(
        self, request: Request, principal: Annotated[Principal, Depends(current_principal)]
    ) -> Principal:
        if not any(p in principal.permissions for p in self.permissions):
            raise ProblemError(403, "forbidden", "You don't have permission to do this")
        if self.step_up:
            settings: IdentitySettings = request.app.state.identity
            if not is_stepped_up(principal.context, settings, datetime.now(UTC)):
                raise ProblemError(
                    403,
                    "step-up-required",
                    "Confirm your password to continue",
                    "Confirm your password, then try again.",
                    max_age_seconds=int(settings.step_up_window.total_seconds()),
                )
        return principal

    def __repr__(self) -> str:
        step_up = ", step_up=True" if self.step_up else ""
        return f"Requires({', '.join(map(repr, self.permissions))}{step_up})"


def requires(*permissions: str, step_up: bool = False) -> Any:
    """`principal: Annotated[Principal, requires("admin.users.manage")]` guards a route."""
    return Depends(Requires(*permissions, step_up=step_up))


@dataclass(frozen=True, slots=True)
class ApiRoute:
    method: str
    path: str
    requirement: Requires | None


def _requirement(dependant: Dependant) -> Requires | None:
    for dependency in dependant.dependencies:
        if isinstance(dependency.call, Requires):
            return dependency.call
        found = _requirement(dependency)
        if found is not None:
            return found
    return None


def _api_contexts(app: FastAPI) -> Iterator[tuple[str, set[str], Dependant]]:
    for context in iter_route_contexts(app.routes):
        path = context.path
        if isinstance(context.original_route, APIRoute) and path and path.startswith(API_PREFIX):
            yield path, context.methods or set(), context.dependant


def api_routes(app: FastAPI) -> list[ApiRoute]:
    """Every method and path under /api/v1, with its guard (or None)."""
    return [
        ApiRoute(method, path, _requirement(dependant))
        for path, methods, dependant in _api_contexts(app)
        for method in sorted(methods - {"HEAD"})
    ]
