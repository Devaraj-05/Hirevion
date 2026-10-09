"""Before the interview (PRD §29, §30, §83, `interview-session.md`): the system check, the
itemised consent and accommodation requests, and a recruiter's decision on them.

System checks and consents are records of what the candidate's desktop reported and what they
agreed to; they're added, never changed. An accommodation approved before the interview starts
changes the interview's policy (`policy.accommodations`), so the briefing, the mandatory checks,
the answer mode and the clock all follow it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.actor import Actor
from hirevion_core.access.errors import Conflict, Invalid, NotFound
from hirevion_core.interview_session.briefing import (
    ACCOMMODATION_KINDS,
    CHECK_NAMES,
    CHECK_STATUSES,
    CONSENT_PURPOSES,
    NOTICE_VERSION,
    mandatory_checks,
    notice_items,
    resume_policy,
)
from hirevion_core.interviews.lifecycle import By, record_event
from hirevion_core.models import Accommodation, Consent, Interview, SystemCheckResult

NOTE_MAX = 2000
VALUE_MAX = 500
# Before the interview starts its policy can still change; afterwards it can't.
DECIDABLE = ("scheduled", "invited")


@dataclass(frozen=True, slots=True)
class CheckReport:
    check: str
    status: str
    value: str | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ConsentAnswer:
    purpose: str
    accepted: bool


def _now() -> datetime:
    return datetime.now(UTC)


def _short(value: str | None, limit: int = VALUE_MAX) -> str | None:
    return value.strip()[:limit] if value and value.strip() else None


async def record_system_check(
    session: AsyncSession,
    interview: Interview,
    *,
    app_version: str,
    os: str,
    results: Sequence[CheckReport],
) -> SystemCheckResult:
    """Stores a system check; it passes when every mandatory check is `pass`."""
    seen: dict[str, CheckReport] = {}
    for item in results:
        if item.check not in CHECK_NAMES:
            raise Invalid("unknown-check", f"Unknown check: {item.check[:40]}", field="results")
        if item.status not in CHECK_STATUSES:
            raise Invalid("invalid-status", "Use pass, warn, fail or skipped", field="results")
        seen[item.check] = item
    failed = [
        c for c in mandatory_checks(interview.policy) if c not in seen or seen[c].status != "pass"
    ]
    row = SystemCheckResult(
        organization_id=interview.organization_id,
        interview_id=interview.id,
        app_version=app_version.strip()[:40],
        os=os.strip()[:200],
        results=[
            {
                "check": item.check,
                "status": item.status,
                "value": _short(item.value),
                "detail": _short(item.detail),
            }
            for item in seen.values()
        ],
        passed=not failed,
        failed_mandatory=failed,
    )
    session.add(row)
    await session.flush()
    return row


async def record_consent(
    session: AsyncSession,
    interview: Interview,
    *,
    notice_version: str,
    answers: Sequence[ConsentAnswer],
    ip: str | None,
    user_agent: str | None,
) -> Consent:
    """Stores the candidate's answers to the current notice. It is complete when every purpose
    the policy requires was accepted."""
    if notice_version != NOTICE_VERSION:
        raise Conflict(
            "notice-outdated",
            "The notice has changed; read it again before agreeing",
            field="notice_version",
        )
    given: dict[str, bool] = {}
    for answer in answers:
        if answer.purpose not in CONSENT_PURPOSES:
            raise Invalid(
                "unknown-purpose", f"Unknown purpose: {answer.purpose[:40]}", field="items"
            )
        given[answer.purpose] = answer.accepted
    notice = notice_items(interview.policy)
    missing = [item.purpose for item in notice if item.required and not given.get(item.purpose)]
    row = Consent(
        organization_id=interview.organization_id,
        interview_id=interview.id,
        candidate_id=interview.candidate_id,
        notice_version=notice_version,
        items=[
            {
                "purpose": item.purpose,
                "accepted": given.get(item.purpose, False),
                "required": item.required,
            }
            for item in notice
        ],
        complete=not missing,
        missing=missing,
        ip=ip,
        user_agent=(user_agent or "")[:500] or None,
    )
    session.add(row)
    await session.flush()
    return row


async def request_accommodation(
    session: AsyncSession,
    interview: Interview,
    kinds: Sequence[str],
    note: str | None,
    by: By,
) -> Accommodation:
    chosen = list(dict.fromkeys(kinds))
    if not chosen:
        raise Invalid("kinds-required", "Choose at least one accommodation", field="kinds")
    unknown = [kind for kind in chosen if kind not in ACCOMMODATION_KINDS]
    if unknown:
        raise Invalid("unknown-kind", f"Unknown accommodation: {unknown[0][:40]}", field="kinds")
    if interview.status not in DECIDABLE:
        raise Conflict("interview-started", "Accommodations are requested before the interview")
    row = Accommodation(
        organization_id=interview.organization_id,
        interview_id=interview.id,
        kinds=chosen,
        note=(note or "").strip()[:NOTE_MAX],
        status="requested",
    )
    session.add(row)
    await session.flush()
    await record_event(
        session,
        interview,
        "accommodation.requested",
        by,
        from_status=interview.status,
        details={"accommodation_id": str(row.id), "kinds": chosen},
    )
    return row


async def list_accommodations(session: AsyncSession, interview_id: UUID) -> list[Accommodation]:
    rows = await session.scalars(
        select(Accommodation)
        .where(Accommodation.interview_id == interview_id)
        .order_by(Accommodation.created_at)
    )
    return list(rows.all())


def apply_accommodations(policy: dict[str, Any], approved: Sequence[str]) -> dict[str, Any]:
    """`policy` with `approved` added: the answer mode and the resume grace follow them."""
    granted = sorted({*(policy.get("accommodations") or []), *approved})
    updated = {**policy, "accommodations": granted}
    if "text_answers" in granted:
        updated["answer_mode"] = "text"
    if "breaks" in granted and not policy.get("breaks_applied"):
        resume = dict(policy.get("resume") or {})
        resume["grace_seconds"] = resume_policy(policy).grace_seconds * 2
        updated["resume"] = resume
        updated["breaks_applied"] = True
    return updated


async def decide_accommodation(
    session: AsyncSession,
    actor: Actor,
    interview: Interview,
    accommodation_id: UUID,
    *,
    approved: Sequence[str],
    note: str | None,
) -> Accommodation:
    """Approves the kinds in `approved` (a subset of those requested); none declines it. The
    interview's event (and so the audit chain) records who decided what."""
    row = await session.get(Accommodation, accommodation_id)
    if row is None or row.interview_id != interview.id:
        raise NotFound("accommodation-not-found", "No such accommodation request")
    if row.status != "requested":
        raise Conflict("already-decided", "This request has already been decided")
    if interview.status not in DECIDABLE:
        raise Conflict("interview-started", "The interview has already started")
    chosen = list(dict.fromkeys(approved))
    extra = [kind for kind in chosen if kind not in row.kinds]
    if extra:
        raise Invalid("not-requested", "Approve only what was requested", field="approved")
    now = _now()
    row.status = "approved" if chosen else "declined"
    row.approved_kinds = chosen
    row.decision_note = (note or "").strip()[:NOTE_MAX] or None
    row.decided_by = actor.user_id
    row.decided_at = now
    if chosen:
        interview.policy = apply_accommodations(dict(interview.policy or {}), chosen)
    await session.flush()
    await record_event(
        session,
        interview,
        f"accommodation.{row.status}",
        By.user(actor),
        from_status=interview.status,
        details={"accommodation_id": str(row.id), "approved": chosen},
    )
    return row
