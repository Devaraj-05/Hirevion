"""Assigning interviews (PRD §24): a candidate for a job plus a template version gives an
interview with §24's nine fields and a pinned policy snapshot (PRD §80). Also rescheduling,
cancelling, reviewers, and reading interviews within the resource scope (ADR-0014).

Bulk assignment creates what it can and skips the rest with a reason, so a recruiter sees which
candidates were left out and why (SP-07a exit criterion).
"""

from __future__ import annotations

import zoneinfo
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Select, delete, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.actor import Actor
from hirevion_core.access.audit import record
from hirevion_core.access.errors import Conflict, Invalid, NotFound
from hirevion_core.access.scope import ResourceScope, scope_clause
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.interviews import invitations
from hirevion_core.interviews.lifecycle import STATUS_GROUPS, By, record_event, transition
from hirevion_core.interviews.templates import PROCTORING_PRESETS
from hirevion_core.models import (
    Application,
    Candidate,
    Interview,
    InterviewEvent,
    InterviewReviewer,
    InterviewTemplate,
    InterviewTemplateVersion,
    Invitation,
    Job,
    Organization,
    User,
)
from hirevion_core.models.interview import ACTIVE_STATUSES
from hirevion_core.outbox import publish_event
from hirevion_core.screening.engine import record_stage

MAX_BULK = 200
MAX_WINDOW = timedelta(days=30)
REASON_MAX = 1000
MAX_REVIEWERS = 10
POLICY_VERSION = 1
# The system checks (PRD §29, and the desktop contract's two extras) a candidate must pass, by
# proctoring level; a required third eye adds its own.
MANDATORY_CHECKS: dict[str, tuple[str, ...]] = {
    "off": ("microphone", "speaker", "network"),
    "basic": ("camera", "microphone", "speaker", "network", "privacy"),
    "standard": (
        "camera",
        "microphone",
        "speaker",
        "screen_capture",
        "network",
        "privacy",
        "media_foundation",
    ),
    "strict": (
        "camera",
        "microphone",
        "speaker",
        "screen_capture",
        "network",
        "displays",
        "privacy",
        "media_foundation",
    ),
}
RESUME_POLICY = {"grace_seconds": 300, "max_interruptions": 3, "pause_timer": True}
UNASSIGNABLE_STAGES = ("uploaded", "rejected")
# Skip codes that mean the request's own input was wrong (a single assignment answers 422).
INPUT_CODES = frozenset({"invalid-window", "window-past", "window-too-short", "window-too-long"})


@dataclass(frozen=True, slots=True)
class Assignment:
    application_ids: Sequence[UUID]
    starts_at: datetime
    expires_at: datetime
    template_id: UUID | None = None
    """None: each job's own interview template (PRD §11)."""
    template_version: int | None = None
    """None: the template's current version."""
    timezone: str | None = None
    reviewer_ids: Sequence[UUID] = ()
    invite: bool = True


@dataclass(frozen=True, slots=True)
class Skipped:
    application_id: UUID
    code: str
    reason: str


@dataclass(slots=True)
class AssignResult:
    created: list[Interview] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class InterviewFilters:
    status_group: str | None = None
    status: str | None = None
    job_id: UUID | None = None
    candidate_id: UUID | None = None
    query: str | None = None
    """Part of the candidate's name or the job's title, or the IV- number."""


@dataclass(frozen=True, slots=True)
class InterviewDetail:
    interview: Interview
    candidate: Candidate
    job: Job
    template_name: str
    reviewers: list[User]
    events: list[InterviewEvent]
    invitations: list[Invitation]


def _now() -> datetime:
    return datetime.now(UTC)


def policy_snapshot(version: InterviewTemplateVersion) -> dict[str, Any]:
    """The interview's operating rules, copied once from its template version: they never change
    afterwards, whatever happens to the template (PRD §80)."""
    level = version.proctoring_level
    mandatory = list(MANDATORY_CHECKS[level])
    if version.third_eye == "required":
        mandatory.append("third_eye")
    return {
        "policy_version": POLICY_VERSION,
        "proctoring_level": level,
        "checks": list(PROCTORING_PRESETS[level]),
        "third_eye": version.third_eye,
        "recording": dict(version.recording),
        "coding": dict(version.coding),
        "question_count": version.question_count,
        "question_types": list(version.question_types),
        "difficulty": dict(version.difficulty),
        "skills": [dict(item) for item in version.skills],
        "use_resume": version.use_resume,
        "use_jd": version.use_jd,
        "adaptive_follow_ups": version.adaptive_follow_ups,
        "rubric": [dict(item) for item in version.rubric],
        "mandatory_checks": mandatory,
        "resume": dict(RESUME_POLICY),
        "answer_mode": "voice",
        "accommodations": [],
    }


def check_window(
    starts_at: datetime, expires_at: datetime, duration_minutes: int, *, now: datetime
) -> None:
    if starts_at.tzinfo is None or expires_at.tzinfo is None:
        raise Invalid("invalid-window", "Give the window with a time zone", field="starts_at")
    if expires_at <= starts_at:
        raise Invalid("invalid-window", "The window must close after it opens", field="expires_at")
    if expires_at <= now:
        raise Invalid("window-past", "The window must close in the future", field="expires_at")
    if expires_at - starts_at < timedelta(minutes=duration_minutes):
        raise Invalid(
            "window-too-short",
            f"The window must be at least the interview's {duration_minutes} minutes long",
            field="expires_at",
        )
    if expires_at - starts_at > MAX_WINDOW:
        raise Invalid("window-too-long", "Keep the window to 30 days at most", field="expires_at")


def _timezone(value: str | None, fallback: str) -> str:
    zone = value or fallback
    if zone not in zoneinfo.available_timezones():
        raise Invalid("invalid-timezone", "Unknown time zone", field="timezone")
    return zone


async def _reviewers(session: AsyncSession, reviewer_ids: Sequence[UUID]) -> list[UUID]:
    ids = list(dict.fromkeys(reviewer_ids))
    if len(ids) > MAX_REVIEWERS:
        raise Invalid("too-many-reviewers", "Choose up to 10 reviewers", field="reviewer_ids")
    if not ids:
        return []
    found = set(
        (
            await session.scalars(
                select(User.id).where(User.id.in_(ids), User.status != "disabled")
            )
        ).all()
    )
    if found != set(ids):
        raise Invalid(
            "invalid-reviewer", "Choose reviewers in this organisation", field="reviewer_ids"
        )
    return ids


async def _version(
    session: AsyncSession, template_id: UUID, version: int | None
) -> InterviewTemplateVersion | None:
    template = await session.get(InterviewTemplate, template_id)
    if template is None or template.status != "active":
        return None
    number = version if version is not None else template.current_version
    return await session.get(InterviewTemplateVersion, (template_id, number))


async def _next_number(session: AsyncSession) -> int:
    current = await session.scalar(select(func.coalesce(func.max(Interview.number), 0)))
    return int(current or 0) + 1


async def _insert(session: AsyncSession, interview: Interview) -> None:
    """Adds the interview with the next free number, retrying if another took it."""
    for _ in range(5):
        interview.number = await _next_number(session)
        try:
            async with session.begin_nested():
                session.add(interview)
                await session.flush()
        except IntegrityError as error:
            if "uq_interviews_organization_id_number" in str(error.orig):
                continue
            if "uq_interviews_active_application" in str(error.orig):
                raise Conflict(
                    "already-assigned", "This candidate already has an interview for this job"
                ) from error
            raise
        return
    raise Conflict("busy", "Too many interviews created at once; try again")


async def _set_reviewers(
    session: AsyncSession, actor: Actor, interview: Interview, reviewer_ids: Sequence[UUID]
) -> None:
    for user_id in reviewer_ids:
        session.add(
            InterviewReviewer(
                organization_id=interview.organization_id,
                interview_id=interview.id,
                user_id=user_id,
                created_by=actor.user_id,
            )
        )
    await session.flush()


async def invite(
    session: AsyncSession,
    actor: Actor | None,
    interview: Interview,
    *,
    settings: IdentitySettings,
    now: datetime | None = None,
) -> Invitation:
    """Sends the invitation: a scheduled interview becomes invited (and its application moves to
    `interview`); an invited one gets its invitation again, with a fresh link."""
    moment = now or _now()
    by = By.user(actor) if actor else By.system()
    if interview.status not in ("scheduled", "invited"):
        raise Conflict(
            "not-invitable", "Only a scheduled or invited interview can be sent its invitation"
        )
    sent = await invitations.send(
        session,
        interview,
        "invitation",
        settings=settings,
        now=moment,
        sent_by=actor.user_id if actor else None,
    )
    if interview.status == "scheduled":
        await transition(session, interview, "invited", "invited", by, now=moment)
        await stage_for_interview(session, interview, actor_id=actor.user_id if actor else None)
    else:
        await record_event(
            session, interview, "invitation.resent", by, from_status=interview.status
        )
    await session.flush()
    return sent


async def _assign_one(
    session: AsyncSession,
    actor: Actor,
    assignment: Assignment,
    application: Application,
    job: Job,
    candidate: Candidate,
    organization: Organization,
    reviewer_ids: list[UUID],
    settings: IdentitySettings,
    now: datetime,
) -> Interview | Skipped:
    def skip(code: str, reason: str) -> Skipped:
        return Skipped(application.id, code, reason)

    if job.status != "open":
        return skip("job-not-open", "The job isn't open")
    if application.stage in UNASSIGNABLE_STAGES:
        return skip("stage", f"Candidates at the {application.stage} stage can't be interviewed")
    if not candidate.email:
        return skip("no-email", "The candidate has no email address to invite")
    active = await session.scalar(
        select(Interview.id).where(
            Interview.application_id == application.id, Interview.status.in_(ACTIVE_STATUSES)
        )
    )
    if active is not None:
        return skip("already-assigned", "The candidate already has an interview for this job")
    template_id = assignment.template_id or job.interview_template_id
    if template_id is None:
        return skip("no-template", "Choose a template, or give the job an interview template")
    version = await _version(session, template_id, assignment.template_version)
    if version is None:
        return skip("template-unavailable", "The template is archived or has no such version")
    try:
        check_window(assignment.starts_at, assignment.expires_at, version.duration_minutes, now=now)
    except Invalid as error:
        return skip(error.code, error.title)
    timezone = _timezone(assignment.timezone, organization.timezone)
    interview = Interview(
        organization_id=application.organization_id,
        number=0,
        application_id=application.id,
        candidate_id=candidate.id,
        job_id=job.id,
        template_id=template_id,
        template_version=version.version,
        status="scheduled",
        starts_at=assignment.starts_at,
        expires_at=assignment.expires_at,
        timezone=timezone,
        locale=organization.default_locale,
        duration_minutes=version.duration_minutes,
        policy=policy_snapshot(version),
        questions=[dict(item) for item in version.questions],
        team_id=job.team_id,
        recruiter_id=job.recruiter_id or actor.user_id,
        created_by=actor.user_id,
        reschedule_count=0,
    )
    try:
        await _insert(session, interview)
    except Conflict as error:
        if error.code == "already-assigned":
            return skip(error.code, error.title)
        raise
    await record_event(
        session,
        interview,
        "created",
        By.user(actor),
        from_status=None,
        details={
            "application_id": str(application.id),
            "template_id": str(template_id),
            "template_version": version.version,
        },
    )
    await publish_event(
        session,
        interview.organization_id,
        "interview.created",
        {
            "interview_id": str(interview.id),
            "candidate_id": str(candidate.id),
            "job_id": str(job.id),
            "application_id": str(application.id),
            "status": interview.status,
        },
        key=str(interview.id),
    )
    await _set_reviewers(session, actor, interview, reviewer_ids)
    if assignment.invite:
        await invite(session, actor, interview, settings=settings, now=now)
    return interview


async def assign(
    session: AsyncSession,
    actor: Actor,
    assignment: Assignment,
    scope: ResourceScope,
    *,
    settings: IdentitySettings,
    now: datetime | None = None,
) -> AssignResult:
    """Creates an interview for each application that can have one; skips the others."""
    moment = now or _now()
    ids = list(dict.fromkeys(assignment.application_ids))
    if not ids or len(ids) > MAX_BULK:
        raise Invalid(
            "invalid-selection",
            f"Choose 1 to {MAX_BULK} candidates",
            field="application_ids",
        )
    if assignment.template_id is not None:
        version = await _version(session, assignment.template_id, assignment.template_version)
        if version is None:
            raise Invalid(
                "template-unavailable",
                "Choose an active template and one of its versions",
                field="template_id",
            )
        check_window(
            assignment.starts_at, assignment.expires_at, version.duration_minutes, now=moment
        )
    reviewer_ids = await _reviewers(session, assignment.reviewer_ids)
    organization = await session.get_one(Organization, actor.organization_id)
    _timezone(assignment.timezone, organization.timezone)
    rows = {
        row[0].id: (row[0], row[1], row[2])
        for row in await session.execute(
            select(Application, Job, Candidate)
            .join(Job, Job.id == Application.job_id)
            .join(Candidate, Candidate.id == Application.candidate_id)
            .where(
                Application.id.in_(ids),
                scope_clause(scope, team_column=Job.team_id, owner_column=Job.recruiter_id),
            )
        )
    }
    result = AssignResult()
    for application_id in ids:
        found = rows.get(application_id)
        if found is None:
            result.skipped.append(
                Skipped(application_id, "application-not-found", "No such application")
            )
            continue
        application, job, candidate = found
        outcome = await _assign_one(
            session,
            actor,
            assignment,
            application,
            job,
            candidate,
            organization,
            reviewer_ids,
            settings,
            moment,
        )
        if isinstance(outcome, Skipped):
            result.skipped.append(outcome)
        else:
            result.created.append(outcome)
    if len(ids) > 1:
        await record(
            session,
            actor,
            "interviews.assigned",
            "organization",
            actor.organization_id,
            details={
                "created": len(result.created),
                "skipped": [
                    {"application_id": str(item.application_id), "code": item.code}
                    for item in result.skipped
                ],
            },
        )
    return result


# Reading


def interviews_statement(
    scope: ResourceScope,
    filters: InterviewFilters,
    *,
    reviewer_only: UUID | None = None,
) -> Select[Interview]:
    """The interviews `scope` reaches that match `filters`; with `reviewer_only`, just those
    that user reviews (the interviewer role). The caller orders and pages it."""
    statement = select(Interview).where(
        scope_clause(scope, team_column=Interview.team_id, owner_column=Interview.recruiter_id)
    )
    if reviewer_only is not None:
        statement = statement.where(
            exists(
                select(InterviewReviewer.user_id).where(
                    InterviewReviewer.interview_id == Interview.id,
                    InterviewReviewer.user_id == reviewer_only,
                )
            )
        )
    if filters.status_group is not None:
        statement = statement.where(Interview.status.in_(STATUS_GROUPS[filters.status_group]))
    if filters.status is not None:
        statement = statement.where(Interview.status == filters.status)
    if filters.job_id is not None:
        statement = statement.where(Interview.job_id == filters.job_id)
    if filters.candidate_id is not None:
        statement = statement.where(Interview.candidate_id == filters.candidate_id)
    if filters.query and filters.query.strip():
        query = filters.query.strip()
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conditions: list[ColumnElement[bool]] = [
            exists(
                select(Candidate.id).where(
                    Candidate.id == Interview.candidate_id,
                    Candidate.name.ilike(f"%{escaped}%", escape="\\"),
                )
            ),
            exists(
                select(Job.id).where(
                    Job.id == Interview.job_id, Job.title.ilike(f"%{escaped}%", escape="\\")
                )
            ),
        ]
        digits = query.upper().removeprefix("IV-").lstrip("0")
        if digits.isdigit() and len(digits) <= 9:
            conditions.append(Interview.number == int(digits))
        statement = statement.where(or_(*conditions))
    return statement


async def get_interview(
    session: AsyncSession,
    interview_id: UUID,
    scope: ResourceScope,
    *,
    reviewer_only: UUID | None = None,
    lock: bool = False,
) -> Interview:
    statement = interviews_statement(scope, InterviewFilters(), reviewer_only=reviewer_only).where(
        Interview.id == interview_id
    )
    if lock:
        statement = statement.with_for_update()
    interview = await session.scalar(statement)
    if interview is None:
        raise NotFound("interview-not-found", "No such interview")
    return interview


async def describe(session: AsyncSession, interview: Interview) -> InterviewDetail:
    candidate = await session.get_one(Candidate, interview.candidate_id)
    job = await session.get_one(Job, interview.job_id)
    template_name = await session.scalar(
        select(InterviewTemplateVersion.name).where(
            InterviewTemplateVersion.template_id == interview.template_id,
            InterviewTemplateVersion.version == interview.template_version,
        )
    )
    template = await session.get(InterviewTemplate, interview.template_id)
    reviewers = (
        await session.scalars(
            select(User)
            .join(InterviewReviewer, InterviewReviewer.user_id == User.id)
            .where(InterviewReviewer.interview_id == interview.id)
            .order_by(User.name)
        )
    ).all()
    events = (
        await session.scalars(
            select(InterviewEvent)
            .where(InterviewEvent.interview_id == interview.id)
            .order_by(InterviewEvent.created_at, InterviewEvent.id)
        )
    ).all()
    sent = (
        await session.scalars(
            select(Invitation)
            .where(Invitation.interview_id == interview.id)
            .order_by(Invitation.created_at, Invitation.id)
        )
    ).all()
    return InterviewDetail(
        interview=interview,
        candidate=candidate,
        job=job,
        template_name=(template.name if template else None) or str(template_name or ""),
        reviewers=list(reviewers),
        events=list(events),
        invitations=list(sent),
    )


# Changing


def _reason(value: str | None, *, required: bool) -> str | None:
    reason = (value or "").strip()[:REASON_MAX] or None
    if required and reason is None:
        raise Invalid("reason-required", "Say why", field="reason")
    return reason


async def reschedule(
    session: AsyncSession,
    actor: Actor,
    interview: Interview,
    starts_at: datetime,
    expires_at: datetime,
    *,
    reason: str | None,
    settings: IdentitySettings,
    now: datetime | None = None,
) -> Interview:
    """A new window. An invited (or expired) interview is invited again with it; a scheduled
    one just takes it. The reminders start over. An expired interview that was never invited
    gets its first invitation, not a "new window" email."""
    moment = now or _now()
    if interview.status not in ("scheduled", "invited", "expired"):
        raise Conflict(
            "not-reschedulable", "Only an interview that hasn't started can be rescheduled"
        )
    check_window(starts_at, expires_at, interview.duration_minutes, now=moment)
    if interview.status == "expired":
        # The candidate may have been given another interview since this one expired.
        other = await session.scalar(
            select(Interview.id).where(
                Interview.application_id == interview.application_id,
                Interview.id != interview.id,
                Interview.status.in_(ACTIVE_STATUSES),
            )
        )
        if other is not None:
            raise Conflict(
                "already-assigned", "This candidate already has another interview for this job"
            )
    note = _reason(reason, required=False)
    previous = {
        "starts_at": interview.starts_at.isoformat(),
        "expires_at": interview.expires_at.isoformat(),
    }
    interview.starts_at = starts_at
    interview.expires_at = expires_at
    interview.reschedule_count += 1
    interview.start_reminder_sent_at = None
    interview.expiry_reminder_sent_at = None
    if interview.status == "expired":
        interview.ended_at = None
    details = {
        "previous": previous,
        "starts_at": starts_at.isoformat(),
        "expires_at": expires_at.isoformat(),
    }
    if interview.status == "scheduled":
        await record_event(
            session,
            interview,
            "rescheduled",
            By.user(actor),
            from_status="scheduled",
            reason=note,
            details=details,
        )
    else:
        never_invited = interview.invited_at is None
        await invitations.send(
            session,
            interview,
            "invitation" if never_invited else "reschedule",
            settings=settings,
            now=moment,
            sent_by=actor.user_id,
            reason=note,
        )
        await transition(
            session,
            interview,
            "invited",
            "rescheduled",
            By.user(actor),
            reason=note,
            details=details,
            now=moment,
        )
        await stage_for_interview(session, interview, actor_id=actor.user_id)
    await session.flush()
    return interview


async def stage_for_interview(
    session: AsyncSession, interview: Interview, *, actor_id: UUID | None
) -> None:
    """An invited candidate's application is at the `interview` stage."""
    application = await session.get_one(Application, interview.application_id)
    if application.stage not in ("interview", "interviewed"):
        await record_stage(
            session, application, "interview", "interview_invited", actor_id=actor_id
        )


async def back_to_shortlist(
    session: AsyncSession,
    interview: Interview,
    action: str,
    *,
    actor_id: UUID | None,
    reason: str | None = None,
) -> None:
    """A cancelled or expired interview returns its candidate to the shortlist, unless another
    interview for the application has moved them on since."""
    application = await session.get_one(Application, interview.application_id)
    other = await session.scalar(
        select(Interview.id).where(
            Interview.application_id == interview.application_id,
            Interview.id != interview.id,
            Interview.status.in_(ACTIVE_STATUSES),
        )
    )
    if application.stage == "interview" and other is None:
        await record_stage(
            session, application, "shortlisted", action, actor_id=actor_id, reason=reason
        )


async def cancel(
    session: AsyncSession,
    actor: Actor,
    interview: Interview,
    *,
    reason: str | None,
    settings: IdentitySettings,
    now: datetime | None = None,
) -> Interview:
    """Cancels an interview that hasn't started; an invited candidate is told. Their
    application goes back to `shortlisted`."""
    moment = now or _now()
    note = _reason(reason, required=True)
    if interview.status not in ("scheduled", "invited"):
        raise Conflict("not-cancellable", "Only an interview that hasn't started can be cancelled")
    was_invited = interview.status == "invited"
    interview.cancel_reason = note
    await transition(
        session, interview, "cancelled", "cancelled", By.user(actor), reason=note, now=moment
    )
    if was_invited:
        candidate = await session.get_one(Candidate, interview.candidate_id)
        # Without an address (removed since) there's no one to tell; the cancel still stands.
        if candidate.email:
            await invitations.send(
                session,
                interview,
                "cancellation",
                settings=settings,
                now=moment,
                sent_by=actor.user_id,
                reason=note,
            )
    await back_to_shortlist(
        session, interview, "interview_cancelled", actor_id=actor.user_id, reason=note
    )
    await session.flush()
    return interview


async def set_reviewers(
    session: AsyncSession, actor: Actor, interview: Interview, reviewer_ids: Sequence[UUID]
) -> list[UUID]:
    ids = await _reviewers(session, reviewer_ids)
    current = set(
        (
            await session.scalars(
                select(InterviewReviewer.user_id).where(
                    InterviewReviewer.interview_id == interview.id
                )
            )
        ).all()
    )
    if current == set(ids):
        return ids
    await session.execute(
        delete(InterviewReviewer).where(
            InterviewReviewer.interview_id == interview.id,
            InterviewReviewer.user_id.not_in(ids)
            if ids
            else InterviewReviewer.user_id.is_not(None),
        )
    )
    await _set_reviewers(session, actor, interview, [user for user in ids if user not in current])
    await record(
        session,
        actor,
        "interview.reviewers.changed",
        "interview",
        interview.id,
        details={
            "added": sorted(str(user) for user in set(ids) - current),
            "removed": sorted(str(user) for user in current - set(ids)),
        },
    )
    return ids
