"""Candidate requests (master plan §6.3; ADR-0022): reschedule, support, accommodation or an
alternative process, the data rights (access, correction, erasure, grievance, nomination) and
consent withdrawal.

A request is stored, audited and acknowledged by email. One about an interview (a reschedule, an
accommodation) is also an event in the interview's history, and an accommodation asked for
before the interview opens SP-09's accommodation request, which the recruiter decides on the
interview's page. Recruiters see requests for the candidates their resource scope reaches, and
move each from open, through in progress, to resolved or declined, with a reply the candidate
reads in the portal.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.actor import Actor
from hirevion_core.access.errors import Conflict, Invalid, NotFound
from hirevion_core.access.scope import ResourceScope
from hirevion_core.audit import AuditEntry, AuditService
from hirevion_core.candidates.candidates import CandidateFilters, candidates_statement
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.interview_session.briefing import ACCOMMODATION_KINDS, CONSENT_PURPOSES
from hirevion_core.interview_session.preparation import DECIDABLE, request_accommodation
from hirevion_core.interviews.lifecycle import By, record_event
from hirevion_core.mail.sender import queue_mail
from hirevion_core.models import (
    Candidate,
    CandidateAccount,
    CandidateRequest,
    Interview,
    Organization,
)
from hirevion_core.models.candidate_portal import (
    CANDIDATE_REQUEST_KINDS,
    CANDIDATE_REQUEST_STATUSES,
)

MESSAGE_MAX = 4000
DETAIL_MAX = 500
# Requests about one interview name it; the rest may.
NEEDS_INTERVIEW = frozenset({"reschedule", "accommodation"})
# Requests that say nothing without words.
NEEDS_MESSAGE = frozenset(
    {"reschedule", "support", "alternative_process", "data_correction", "grievance"}
)
# An interview that has run can't be moved.
NOT_RESCHEDULABLE = frozenset({"completed", "evaluating", "evaluated", "cancelled"})
FINAL = frozenset({"resolved", "declined"})
# What each kind may carry in `details`; anything else is dropped.
_TEXT_DETAILS: dict[str, tuple[str, ...]] = {
    "reschedule": ("preferred",),
    "nomination": ("nominee_name", "nominee_email", "relationship"),
    "data_correction": ("field",),
}
KIND_LABELS: dict[str, str] = {
    "reschedule": "Reschedule an interview",
    "support": "Support",
    "accommodation": "Accommodation",
    "alternative_process": "Alternative process",
    "data_access": "A copy of my data",
    "data_correction": "Correct my data",
    "data_erasure": "Delete my data",
    "grievance": "Grievance",
    "nomination": "Nominate someone",
    "consent_withdrawal": "Withdraw consent",
}

_audit = AuditService()


@dataclass(frozen=True, slots=True)
class NewRequest:
    kind: str
    message: str
    interview_id: UUID | None = None
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RequestFilters:
    status: str | None = None
    kind: str | None = None
    interview_id: UUID | None = None
    candidate_id: UUID | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _text(value: Any) -> str:
    return value.strip()[:DETAIL_MAX] if isinstance(value, str) else ""


def _choices(value: Any, allowed: tuple[str, ...], name: str) -> list[str]:
    chosen = list(dict.fromkeys(value)) if isinstance(value, list) else []
    if not chosen:
        raise Invalid(f"{name}-required", f"Choose at least one of the {name}", field=name)
    unknown = [item for item in chosen if item not in allowed]
    if unknown:
        raise Invalid(f"unknown-{name}", f"Unknown choice: {str(unknown[0])[:40]}", field=name)
    return chosen


def _details(new: NewRequest) -> dict[str, Any]:
    """The kind's own details, checked; everything else dropped."""
    details: dict[str, Any] = {}
    for name in _TEXT_DETAILS.get(new.kind, ()):
        value = _text(new.details.get(name))
        if value:
            details[name] = value
    if new.kind == "accommodation":
        details["kinds"] = _choices(new.details.get("kinds"), ACCOMMODATION_KINDS, "kinds")
    if new.kind == "consent_withdrawal":
        details["purposes"] = _choices(new.details.get("purposes"), CONSENT_PURPOSES, "purposes")
    if new.kind == "nomination":
        email = details.get("nominee_email", "")
        if not details.get("nominee_name") or "@" not in email:
            raise Invalid(
                "nominee-required", "Give the nominee's name and email", field="nominee_name"
            )
    return details


async def _own_interview(
    session: AsyncSession, account: CandidateAccount, interview_id: UUID
) -> Interview:
    interview = await session.get(Interview, interview_id)
    if interview is None or interview.candidate_id != account.candidate_id:
        raise NotFound("interview-not-found", "No such interview")
    return interview


async def create_request(
    session: AsyncSession,
    account: CandidateAccount,
    new: NewRequest,
    *,
    ip: str | None,
    user_agent: str | None,
    settings: IdentitySettings | None = None,
) -> CandidateRequest:
    if new.kind not in CANDIDATE_REQUEST_KINDS:
        raise Invalid("unknown-kind", "Unknown kind of request", field="kind")
    message = new.message.strip()[:MESSAGE_MAX]
    if new.kind in NEEDS_MESSAGE and not message:
        raise Invalid("message-required", "Say what you need", field="message")
    if new.kind in NEEDS_INTERVIEW and new.interview_id is None:
        raise Invalid("interview-required", "Choose the interview", field="interview_id")
    details = _details(new)
    interview = (
        await _own_interview(session, account, new.interview_id)
        if new.interview_id is not None
        else None
    )
    if new.kind == "reschedule" and interview is not None and interview.status in NOT_RESCHEDULABLE:
        raise Conflict("interview-not-reschedulable", "This interview can't be rescheduled")
    by = By("candidate", str(account.id), ip, user_agent)
    opened = False
    if new.kind == "accommodation" and interview is not None and interview.status in DECIDABLE:
        # Its own event (`accommodation.requested`) goes on the interview's history.
        accommodation = await request_accommodation(
            session, interview, details["kinds"], message, by
        )
        details["accommodation_id"] = str(accommodation.id)
        opened = True
    row = CandidateRequest(
        organization_id=account.organization_id,
        account_id=account.id,
        candidate_id=account.candidate_id,
        interview_id=interview.id if interview is not None else None,
        kind=new.kind,
        status="open",
        message=message,
        details=details,
    )
    session.add(row)
    await session.flush()
    if interview is not None and not opened:
        await record_event(
            session,
            interview,
            f"{new.kind}.requested",
            by,
            from_status=interview.status,
            details={"request_id": str(row.id)},
        )
    await _audit.append(
        session,
        account.organization_id,
        AuditEntry(
            action="candidate.request.created",
            resource_type="candidate_request",
            resource_id=str(row.id),
            actor_type="candidate",
            actor_id=str(account.id),
            ip=ip,
            user_agent=user_agent,
            details={"kind": new.kind},
        ),
    )
    await _acknowledge(session, account, row, settings or IdentitySettings())
    return row


async def _acknowledge(
    session: AsyncSession,
    account: CandidateAccount,
    row: CandidateRequest,
    settings: IdentitySettings,
) -> None:
    organization = await session.get_one(Organization, account.organization_id)
    await queue_mail(
        session,
        organization_id=account.organization_id,
        template="candidate_request_received",
        to=account.email,
        locale=account.locale,
        context={
            "name": account.name,
            "organization": organization.name,
            "kind": KIND_LABELS[row.kind],
            "reference": reference(row.id),
            "requests_link": f"{settings.candidate_origin.rstrip('/')}/requests",
            "support_email": organization.support_email or settings.support_email,
        },
    )


def reference(request_id: UUID) -> str:
    """How people quote a request: RQ- and the end of its id (UUIDv7's random part)."""
    return f"RQ-{request_id.hex[-8:].upper()}"


async def list_own(session: AsyncSession, account_id: UUID) -> list[CandidateRequest]:
    """The candidate's requests, newest first."""
    rows = await session.scalars(
        select(CandidateRequest)
        .where(CandidateRequest.account_id == account_id)
        .order_by(CandidateRequest.created_at.desc(), CandidateRequest.id.desc())
        .limit(200)
    )
    return list(rows.all())


def recruiter_statement(scope: ResourceScope, filters: RequestFilters) -> Select[CandidateRequest]:
    """Requests of the candidates `scope` reaches that match `filters`; the caller orders them."""
    reachable = candidates_statement(scope, CandidateFilters()).with_only_columns(Candidate.id)
    statement = select(CandidateRequest).where(CandidateRequest.candidate_id.in_(reachable))
    if filters.status is not None:
        statement = statement.where(CandidateRequest.status == filters.status)
    if filters.kind is not None:
        statement = statement.where(CandidateRequest.kind == filters.kind)
    if filters.interview_id is not None:
        statement = statement.where(CandidateRequest.interview_id == filters.interview_id)
    if filters.candidate_id is not None:
        statement = statement.where(CandidateRequest.candidate_id == filters.candidate_id)
    return statement


async def update_request(
    session: AsyncSession,
    actor: Actor,
    scope: ResourceScope,
    request_id: UUID,
    *,
    status: str,
    response: str | None,
) -> CandidateRequest:
    """Moves a request on (open → in progress → resolved or declined), with a reply."""
    row = await session.scalar(
        recruiter_statement(scope, RequestFilters()).where(CandidateRequest.id == request_id)
    )
    if row is None:
        raise NotFound("request-not-found", "No such request")
    if status not in CANDIDATE_REQUEST_STATUSES or status == "open":
        raise Invalid("invalid-status", "Choose in progress, resolved or declined", field="status")
    if row.status in FINAL:
        raise Conflict("request-closed", "This request is already closed")
    reply = (response or "").strip()[:MESSAGE_MAX]
    previous = row.status
    row.status = status
    if reply:
        row.response = reply
    row.handled_by = actor.user_id
    row.handled_at = _now()
    await session.flush()
    await _audit.append(
        session,
        row.organization_id,
        AuditEntry(
            action="candidate.request.updated",
            resource_type="candidate_request",
            resource_id=str(row.id),
            actor_type="user",
            actor_id=str(actor.user_id),
            ip=actor.ip,
            user_agent=actor.user_agent,
            details={"from": previous, "to": status, "replied": bool(reply)},
        ),
    )
    return row


__all__ = [
    "KIND_LABELS",
    "NewRequest",
    "RequestFilters",
    "create_request",
    "list_own",
    "recruiter_statement",
    "reference",
    "update_request",
]
