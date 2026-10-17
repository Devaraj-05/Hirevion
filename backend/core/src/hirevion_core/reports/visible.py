"""The candidate-visible report (PRD §99; ADR-0023): the five things an organisation may show a
candidate about their interview, and only after a recruiter approves each release.

- **The organisation chooses** which of the five items may ever be shown
  (`organization_settings.candidate_report`).
- **A draft** is written from the evaluation in plain words, with no scores, no flags and nothing
  from proctoring, and a recruiter edits it.
- **Approving** freezes what the organisation allows into `released_items`. The portal reads
  that and nothing else, so a later change to the evaluation, the draft or the hiring status
  never changes what a candidate was shown; withdrawing hides it again.
- **Internal reports stay internal**: nothing here reads a note, a score change, a hiring input,
  a proctoring event or a recording.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.actor import Actor
from hirevion_core.access.audit import record
from hirevion_core.access.errors import Conflict, Invalid
from hirevion_core.models import Interview, Job, OrganizationSettings, Report
from hirevion_core.reports import blocks as b
from hirevion_core.reports.blocks import Document
from hirevion_core.reports.data import InterviewData

ITEMS = ("completion", "general_feedback", "technical_feedback", "coding_feedback", "next_step")
ITEM_TITLES = {
    "completion": "Interview completion",
    "general_feedback": "General feedback",
    "technical_feedback": "Technical feedback",
    "coding_feedback": "Coding feedback",
    "next_step": "Next step",
}
DEFAULT_ITEMS = {
    "completion": True,
    "general_feedback": False,
    "technical_feedback": False,
    "coding_feedback": False,
    "next_step": True,
}
TEXT_MAX = 4000
FINISHED = ("completed", "evaluating", "evaluated")
NEXT_STEP = {
    "under_review": "Thank you for your interview. We are reviewing it and will be in touch.",
    "shortlisted": "You remain on our shortlist. We will tell you what happens next.",
    "interview_invited": "Your interview is booked. We will tell you what happens next.",
    "interview_started": "Your interview is being recorded as in progress.",
    "interview_completed": "Thank you for your interview. We are reviewing it and will be in "
    "touch.",
    "additional_review": "Your interview is going through an additional review. We will be in "
    "touch.",
    "on_hold": "Your application is on hold for now. We will tell you when that changes.",
    "selected": "We would like to move forward with you. Your recruiter will contact you.",
    "rejected": "We will not be taking your application further this time. Thank you for the "
    "time you gave us.",
}


# The organisation's choice.


async def allowed_items(session: AsyncSession, organization_id: UUID) -> dict[str, bool]:
    """Which of the five items the organisation lets recruiters release."""
    row = await session.get(OrganizationSettings, organization_id)
    saved = ((row.candidate_report if row else None) or {}).get("items") or {}
    return {item: bool(saved.get(item, DEFAULT_ITEMS[item])) for item in ITEMS}


async def save_allowed_items(
    session: AsyncSession, actor: Actor, items: Mapping[str, bool]
) -> dict[str, bool]:
    unknown = sorted(set(items) - set(ITEMS))
    if unknown:
        raise Invalid("unknown-item", f"Unknown item: {', '.join(unknown)}", field="items")
    before = await allowed_items(session, actor.organization_id)
    chosen = {item: bool(items.get(item, before[item])) for item in ITEMS}
    row = await session.get(OrganizationSettings, actor.organization_id)
    if row is None:
        row = OrganizationSettings(organization_id=actor.organization_id)
        session.add(row)
    row.candidate_report = {"items": chosen}
    row.updated_by = actor.user_id
    await session.flush()
    await record(
        session,
        actor,
        "organization.candidate_report_changed",
        "organization",
        actor.organization_id,
        details={"before": before, "after": chosen},
    )
    return chosen


# The draft.


def _sentences(items: list[dict[str, Any]], limit: int = 3) -> list[str]:
    return [
        str(item["text"]).strip() for item in items[:limit] if str(item.get("text", "")).strip()
    ]


def draft_items(data: InterviewData) -> dict[str, dict[str, Any]]:
    """A draft of the five items, in words a candidate can read. No scores, flags or integrity
    signals ever go into it; the recruiter edits it before approving."""
    interview, job = data.interview, data.job
    tz = data.timezone
    summary = data.evaluation.summary if data.evaluation is not None else {}
    strengths = _sentences(summary.get("strengths", []))
    gaps = _sentences(summary.get("knowledge_gaps", []))
    finished = interview.ended_at or interview.completed_at
    drafts = {
        "completion": f"You completed your interview for {job.title} on {b.day(finished, tz)}. "
        "Thank you for the time you gave it.",
        "general_feedback": (
            "Thank you for your interview. Things that stood out: " + " ".join(strengths)
            if strengths
            else "Thank you for your interview."
        ),
        "technical_feedback": (
            "Areas you could build on: " + " ".join(gaps)
            if gaps
            else "We have no specific technical feedback to share from this interview."
        ),
        "coding_feedback": "There was no coding assessment in this interview.",
        "next_step": NEXT_STEP[data.application.hiring_status],
    }
    return {
        item: {"text": drafts[item], "include": item in ("completion", "next_step")}
        for item in ITEMS
    }


def _clean_items(items: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    unknown = sorted(set(items) - set(ITEMS))
    if unknown:
        raise Invalid("unknown-item", f"Unknown item: {', '.join(unknown)}", field="items")
    cleaned: dict[str, dict[str, Any]] = {}
    for item, value in items.items():
        text = str(value.get("text", "")).strip()
        if len(text) > TEXT_MAX:
            raise Invalid("text-too-long", f"At most {TEXT_MAX} characters", field=item)
        cleaned[item] = {"text": text, "include": bool(value.get("include"))}
    return cleaned


async def get_report(session: AsyncSession, interview_id: UUID) -> Report | None:
    return await session.scalar(select(Report).where(Report.interview_id == interview_id))


def _check_finished(interview: Interview) -> None:
    if interview.status not in FINISHED:
        raise Conflict("not-finished", "Only an interview that has ended has a report")


async def save_draft(
    session: AsyncSession,
    actor: Actor,
    data: InterviewData,
    items: Mapping[str, Mapping[str, Any]],
) -> Report:
    """Creates or updates the draft; a released report must be withdrawn before it is edited."""
    interview = data.interview
    _check_finished(interview)
    report = await get_report(session, interview.id)
    chosen = {**draft_items(data), **(report.items if report else {}), **_clean_items(items)}
    if report is None:
        report = Report(
            organization_id=interview.organization_id,
            interview_id=interview.id,
            application_id=interview.application_id,
            evaluation_id=data.evaluation.id if data.evaluation else None,
            items=chosen,
        )
        session.add(report)
    else:
        if report.status == "released":
            raise Conflict("released", "Withdraw the report before editing it")
        report.items = chosen
        report.status = "draft"
    await session.flush()
    await session.refresh(report)
    await record(
        session,
        actor,
        "report.draft_saved",
        "interview",
        interview.id,
        details={"included": [k for k, v in chosen.items() if v.get("include")]},
    )
    return report


async def approve(session: AsyncSession, actor: Actor, data: InterviewData) -> Report:
    """A recruiter releases the report: what the organisation allows and the recruiter included,
    frozen as it reads now."""
    interview = data.interview
    _check_finished(interview)
    allowed = await allowed_items(session, interview.organization_id)
    report = await get_report(session, interview.id)
    if report is None:
        report = await save_draft(session, actor, data, {})
    if report.status == "released":
        raise Conflict("released", "That report is already released")
    released = {
        item: {"title": ITEM_TITLES[item], "text": value["text"]}
        for item, value in report.items.items()
        if allowed.get(item) and value.get("include") and str(value.get("text", "")).strip()
    }
    if not released:
        raise Conflict("nothing-to-release", "Nothing is both allowed and included to release")
    report.status = "released"
    report.released_items = released
    report.approved_by = actor.user_id
    report.approved_at = datetime.now(UTC)
    report.withdrawn_at = report.withdrawn_by = report.withdrawn_reason = None
    await session.flush()
    await session.refresh(report)
    await record(
        session,
        actor,
        "report.released",
        "interview",
        interview.id,
        details={"items": sorted(released), "candidate_id": str(interview.candidate_id)},
    )
    return report


async def withdraw(
    session: AsyncSession, actor: Actor, interview: Interview, reason: str
) -> Report:
    report = await get_report(session, interview.id)
    note = reason.strip()
    if report is None or report.status != "released":
        raise Conflict("not-released", "That report isn't released")
    if not note:
        raise Invalid("reason-required", "Say why it is being withdrawn", field="reason")
    report.status = "withdrawn"
    report.withdrawn_at = datetime.now(UTC)
    report.withdrawn_by = actor.user_id
    report.withdrawn_reason = note
    await session.flush()
    await session.refresh(report)
    await record(
        session,
        actor,
        "report.withdrawn",
        "interview",
        interview.id,
        details={"reason": note, "candidate_id": str(interview.candidate_id)},
    )
    return report


# What the candidate sees.


async def released_reports(
    session: AsyncSession, candidate_id: UUID
) -> list[tuple[Interview, Job, Report]]:
    """The candidate's released reports, newest first. Nothing else about an interview is read."""
    rows = await session.execute(
        select(Interview, Job, Report)
        .join(Report, Report.interview_id == Interview.id)
        .join(Job, Job.id == Interview.job_id)
        .where(Interview.candidate_id == candidate_id, Report.status == "released")
        .order_by(Report.approved_at.desc())
    )
    return [(row[0], row[1], row[2]) for row in rows]


def visible_document(interview: Interview, job: Job, report: Report) -> Document:
    """The released items as a document: no internal section can appear in it, because only
    `released_items` goes in."""
    items = report.released_items or {}
    sections = [
        b.section(item, ITEM_TITLES[item], [b.text(items[item]["text"])])
        for item in ITEMS
        if item in items
    ]
    return b.document(
        "candidate_visible",
        "Your interview feedback",
        f"{job.title} · IV-{interview.number:04d}",
        sections,
        audience="candidate",
        subject={"interview_id": str(interview.id), "job_title": job.title},
        generated_at=report.approved_at,
    )
