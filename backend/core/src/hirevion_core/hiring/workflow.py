"""The hiring workflow (PRD §72, ADR-0023): the nine statuses of an application, each change kept
in `application_status_history` and in the audit log.

- **System-driven.** `interview_invited`, `interview_started` and `interview_completed` report
  facts about the interview, so nobody chooses them: `sync_from_stage` follows the screening
  stage (`record_stage` calls it) and `sync_interview` follows the interview's own lifecycle.
- **Person-driven.** A recruiter moves the rest (`change_status`). `shortlisted`, `under_review`,
  `on_hold` and a rejection before any interview go through the screening actions, so the stage
  and its audit stay as SP-05 wrote them. `additional_review`, `selected` and a rejection after an
  interview are decisions about the interview: the last two are the **final decision** and need
  `hiring.decide`, a reason and, for `selected`, a finished interview. The AI never decides.
- **A decision stands.** The system never moves a `selected` application; only someone who may
  decide can reopen one.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.actor import Actor
from hirevion_core.access.audit import record
from hirevion_core.access.errors import Conflict, Invalid, NotFound, Refused
from hirevion_core.models import Application, ApplicationStatusHistory, Interview
from hirevion_core.models.candidate import HIRING_STATUSES

SYSTEM_ONLY = frozenset({"interview_invited", "interview_started", "interview_completed"})
DECISION_STATUSES = frozenset({"selected", "rejected"})
# What a person may choose, in the order the pipeline offers them.
MANUAL_ORDER = (
    "under_review",
    "shortlisted",
    "additional_review",
    "selected",
    "rejected",
    "on_hold",
)
STAGE_STATUS = {
    "uploaded": "under_review",
    "parsed": "under_review",
    "screened": "under_review",
    "ranked": "under_review",
    "review": "under_review",
    "shortlisted": "shortlisted",
    "rejected": "rejected",
    "on_hold": "on_hold",
    "interview": "interview_invited",
    "interviewed": "interview_completed",
}
# The screening stage and action that keep `stage` in step when a person picks a status.
STATUS_STAGE = {
    "under_review": ("review", "review"),
    "shortlisted": ("shortlisted", "shortlist"),
    "on_hold": ("on_hold", "hold"),
    "rejected": ("rejected", "reject"),
}
REASON_REQUIRED = frozenset({"additional_review", "on_hold", "selected", "rejected"})
REASON_MAX = 1000
FINISHED = ("completed", "evaluating", "evaluated")
LIVE = ("in_progress", "interrupted")
BEFORE_INTERVIEW = ("under_review", "shortlisted", "interview_invited", "interview_started")
# What a person decided about an application: the system's facts about the interview don't undo it.
HELD_BY_PEOPLE = frozenset({"rejected", "on_hold", "additional_review"})

__all__ = [
    "DECISION_STATUSES",
    "HIRING_STATUSES",
    "SYSTEM_ONLY",
    "allowed_targets",
    "change_status",
    "finished_interview",
    "status_for_stage",
    "sync_from_stage",
    "sync_interview",
]


def status_for_stage(stage: str) -> str | None:
    return STAGE_STATUS.get(stage)


def _add_history(
    session: AsyncSession,
    application: Application,
    target: str,
    *,
    actor_id: object | None,
    reason: str | None,
    interview_id: object | None = None,
    decision: bool = False,
) -> ApplicationStatusHistory:
    row = ApplicationStatusHistory(
        organization_id=application.organization_id,
        application_id=application.id,
        interview_id=interview_id,
        from_status=application.hiring_status,
        to_status=target,
        source="user" if actor_id is not None else "system",
        reason=reason,
        actor_id=actor_id,
        decision=decision,
    )
    session.add(row)
    application.hiring_status = target
    return row


async def sync_from_stage(
    session: AsyncSession,
    application: Application,
    *,
    actor_id: object | None = None,
    reason: str | None = None,
) -> None:
    """Follows a change of the screening stage: called by `record_stage` once the stage changes.
    A person's move names them; the system's own facts about the interview never undo what a
    person decided (a rejection, a hold, a review request)."""
    target = STAGE_STATUS.get(application.stage)
    if target is None or target == application.hiring_status:
        return
    current = application.hiring_status
    if current == "selected":
        return
    if actor_id is None and target in SYSTEM_ONLY and current in HELD_BY_PEOPLE:
        return
    _add_history(session, application, target, actor_id=actor_id, reason=reason)


async def sync_interview(session: AsyncSession, interview: Interview) -> None:
    """Follows the interview's lifecycle: running means `interview_started`, an abandoned one
    goes back to `interview_invited` and a finished one is `interview_completed`. An application
    a person rejected, put on hold or sent to further review stays as they left it."""
    application = await session.get(Application, interview.application_id)
    if application is None or application.hiring_status == "selected":
        return
    current = application.hiring_status
    target: str | None = None
    if (
        interview.status in LIVE
        and current != "interview_started"
        and current not in HELD_BY_PEOPLE
    ):
        target = "interview_started"
    elif interview.status == "abandoned" and current == "interview_started":
        target = "interview_invited"
    elif interview.status in FINISHED and current in BEFORE_INTERVIEW:
        target = "interview_completed"
    if target is not None:
        _add_history(
            session, application, target, actor_id=None, reason=None, interview_id=interview.id
        )


async def finished_interview(session: AsyncSession, application_id: object) -> Interview | None:
    """The application's most recent interview that has ended, if any."""
    return await session.scalar(
        select(Interview)
        .where(Interview.application_id == application_id, Interview.status.in_(FINISHED))
        .order_by(Interview.completed_at.desc().nulls_last(), Interview.created_at.desc())
        .limit(1)
    )


def allowed_targets(
    current: str, *, can_decide: bool, has_interview: bool, can_manage: bool = True
) -> list[str]:
    """What a person may move an application at `current` to: the pipeline's menu."""
    if not can_manage:
        return []
    # Moving out of a decision is reopening it, which only someone who may decide can do.
    if (current == "selected" or (current == "rejected" and has_interview)) and not can_decide:
        return []
    targets: list[str] = []
    for status in MANUAL_ORDER:
        if status == current:
            continue
        if status == "selected" and not (can_decide and has_interview):
            continue
        if status == "rejected" and has_interview and not can_decide:
            continue
        targets.append(status)
    return targets


def _reason(value: str | None) -> str | None:
    return (value or "").strip()[:REASON_MAX] or None


async def change_status(
    session: AsyncSession,
    actor: Actor,
    application_id: object,
    target: str,
    *,
    reason: str | None,
) -> ApplicationStatusHistory:
    """A person's change of an application's hiring status, validated, recorded and audited.
    Returns the history row it wrote."""
    if target not in HIRING_STATUSES:
        raise Invalid("unknown-status", "That isn't a hiring status", field="status")
    if target in SYSTEM_ONLY:
        raise Conflict(
            "system-status", "That status follows the interview itself and can't be chosen"
        )
    # Locked and re-read: a status another request just changed must not be judged from a stale
    # copy (the route may have loaded the application already).
    application = await session.scalar(
        select(Application)
        .where(Application.id == application_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if application is None:
        raise NotFound("application-not-found", "No such application")
    previous = application.hiring_status
    if target == previous:
        raise Conflict("no-change", "The application already has that status")
    note = _reason(reason)
    if target in REASON_REQUIRED and note is None:
        raise Invalid("reason-required", "Say why", field="reason")
    interview = await finished_interview(session, application.id)
    after_interview = interview is not None
    decisive = after_interview and target in DECISION_STATUSES
    reopening = previous == "selected" or (previous == "rejected" and after_interview)
    if (decisive or reopening or target == "selected") and "hiring.decide" not in actor.permissions:
        raise Refused("decision-forbidden", "Only someone authorised to decide can do this")
    if target == "selected" and not after_interview:
        raise Conflict("no-interview", "Select a candidate only after their interview")

    stage = STATUS_STAGE.get(target)
    if decisive or reopening or target in ("additional_review", "selected"):
        row = _add_history(
            session,
            application,
            target,
            actor_id=actor.user_id,
            reason=note,
            interview_id=interview.id if interview is not None else None,
            decision=decisive or reopening,
        )
        if stage is not None:
            from hirevion_core.screening.engine import record_stage

            await record_stage(
                session, application, stage[0], stage[1], actor_id=actor.user_id, reason=note
            )
    elif stage is not None:  # every other target is a screening action
        from hirevion_core.screening.workflow import act

        await act(session, actor, application.job_id, [application.id], stage[1], reason=note)
        latest = await session.scalar(
            select(ApplicationStatusHistory)
            .where(ApplicationStatusHistory.application_id == application.id)
            .order_by(
                ApplicationStatusHistory.created_at.desc(), ApplicationStatusHistory.id.desc()
            )
            .limit(1)
        )
        if latest is None or application.hiring_status != target:
            latest = _add_history(session, application, target, actor_id=actor.user_id, reason=note)
        row = latest
    else:
        raise Invalid("unknown-status", "That isn't a hiring status", field="status")
    await session.flush()
    details: dict[str, object] = {
        "candidate_id": str(application.candidate_id),
        "job_id": str(application.job_id),
        "interview_id": str(row.interview_id) if row.interview_id else None,
        "from": previous,
        "to": target,
        "reason": note,
    }
    if row.decision:
        details["decision"] = target
    await record(
        session,
        actor,
        "hiring.decided" if row.decision else "hiring.status_changed",
        "application",
        application.id,
        details=details,
    )
    return row
