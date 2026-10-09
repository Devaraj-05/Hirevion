"""The interview scheduler (SP-07a): reminders and expiry, run by the worker every minute.

It reminds a candidate 24 hours before their window opens (when the invitation went out before
that) and 24 hours before an unstarted window closes, once each, and expires scheduled or
invited interviews whose window has closed. `scheduler_due_interviews` lists what's due in every
organisation (a SECURITY DEFINER function owned by `hirevion_scheduler`); each interview is then
handled in its own tenant's transaction under `FOR UPDATE SKIP LOCKED`, and checked again there,
so two workers never send the same reminder twice. SP-18's scheduler takes this loop over.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.errors import Invalid
from hirevion_core.db.session import Database
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.interviews import invitations
from hirevion_core.interviews.assignment import back_to_shortlist
from hirevion_core.interviews.lifecycle import By, record_event, transition
from hirevion_core.models import Interview

log = logging.getLogger(__name__)

REMINDER_LEAD = timedelta(hours=24)
BATCH = 200


@dataclass(slots=True)
class SchedulerReport:
    expired: int = 0
    start_reminders: int = 0
    expiry_reminders: int = 0

    @property
    def total(self) -> int:
        return self.expired + self.start_reminders + self.expiry_reminders


async def due_interviews(
    db: Database, now: datetime, lead: timedelta = REMINDER_LEAD, limit: int = BATCH
) -> list[tuple[UUID, UUID]]:
    async with db.unscoped() as session:
        rows = await session.execute(
            text("SELECT * FROM scheduler_due_interviews(:now, :lead, :limit)"),
            {"now": now, "lead": lead, "limit": limit},
        )
        return [(row.organization_id, row.interview_id) for row in rows]


async def _remind(
    session: AsyncSession,
    interview: Interview,
    settings: IdentitySettings,
    now: datetime,
    reminder: Literal["opens", "closes"],
) -> bool:
    """Sends a reminder; False if there was nobody to send it to (the address was removed),
    which is recorded so the scheduler doesn't try again every minute."""
    try:
        async with session.begin_nested():
            await invitations.send(
                session, interview, "reminder", settings=settings, now=now, reminder=reminder
            )
    except Invalid as error:
        if error.code != "no-email":
            raise
        await record_event(
            session,
            interview,
            "reminder.skipped",
            By.system(),
            from_status=interview.status,
            reason="The candidate has no email address",
        )
        return False
    return True


async def _handle(
    session: AsyncSession,
    interview: Interview,
    settings: IdentitySettings,
    now: datetime,
    lead: timedelta,
    report: SchedulerReport,
) -> None:
    if interview.status in ("scheduled", "invited") and interview.expires_at <= now:
        await transition(session, interview, "expired", "expired", By.system(), now=now)
        await back_to_shortlist(session, interview, "interview_expired", actor_id=None)
        report.expired += 1
        return
    if interview.status != "invited":
        return
    if (
        interview.start_reminder_sent_at is None
        and now < interview.starts_at <= now + lead
        and interview.invited_at is not None
        and interview.invited_at <= interview.starts_at - lead
    ):
        interview.start_reminder_sent_at = now
        if await _remind(session, interview, settings, now, "opens"):
            report.start_reminders += 1
    elif (
        interview.expiry_reminder_sent_at is None
        and interview.starts_at <= now < interview.expires_at <= now + lead
        and interview.expires_at - interview.starts_at > lead
    ):
        interview.expiry_reminder_sent_at = now
        if await _remind(session, interview, settings, now, "closes"):
            report.expiry_reminders += 1


async def run_due(
    db: Database,
    settings: IdentitySettings,
    *,
    now: datetime | None = None,
    lead: timedelta = REMINDER_LEAD,
) -> SchedulerReport:
    """Handles everything due now; returns what it did."""
    moment = now or datetime.now(UTC)
    report = SchedulerReport()
    for organization_id, interview_id in await due_interviews(db, moment, lead):
        try:
            async with db.tenant(organization_id) as session:
                interview = await session.scalar(
                    select(Interview)
                    .where(Interview.id == interview_id)
                    .with_for_update(skip_locked=True)
                )
                if interview is not None:
                    await _handle(session, interview, settings, moment, lead, report)
        except Exception:
            log.exception("The scheduler couldn't handle interview %s", interview_id)
    return report


class InterviewScheduler:
    def __init__(self, db: Database, settings: IdentitySettings, interval: float = 60) -> None:
        self._db = db
        self._settings = settings
        self._interval = interval

    async def run_forever(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                report = await run_due(self._db, self._settings)
                if report.total:
                    log.info(
                        "Scheduler: %d expired, %d opening and %d closing reminders",
                        report.expired,
                        report.start_reminders,
                        report.expiry_reminders,
                    )
            except Exception:
                log.exception("The interview scheduler failed; retrying")
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), self._interval)
