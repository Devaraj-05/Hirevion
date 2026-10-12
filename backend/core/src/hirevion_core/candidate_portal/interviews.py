"""The candidate's interviews as the portal shows them (master plan §6.3 "Interview status and
window"): every interview they were invited to, with its window and whether it can be taken
now. Times are UTC with the interview's time zone; the page formats them for its language."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.candidate_access.service import AVAILABLE, window_end
from hirevion_core.interviews.invitations import recorded
from hirevion_core.interviews.lifecycle import reference
from hirevion_core.models import CandidateAccount, Interview, Job


@dataclass(frozen=True, slots=True)
class PortalInterview:
    id: UUID
    reference: str
    job_title: str
    status: str
    starts_at: datetime
    expires_at: datetime
    timezone: str
    duration_minutes: int
    can_take: bool
    third_eye: str
    recorded: str


async def portal_interviews(
    session: AsyncSession, account: CandidateAccount, now: datetime
) -> list[PortalInterview]:
    """Soonest window first. Interviews not yet sent to the candidate aren't theirs to see."""
    rows = await session.execute(
        select(Interview, Job)
        .join(Job, Job.id == Interview.job_id)
        .where(Interview.candidate_id == account.candidate_id, Interview.status != "scheduled")
        .order_by(Interview.starts_at, Interview.id)
    )
    return [
        PortalInterview(
            id=interview.id,
            reference=reference(interview.number),
            job_title=job.title,
            status=interview.status,
            starts_at=interview.starts_at,
            expires_at=interview.expires_at,
            timezone=interview.timezone,
            duration_minutes=interview.duration_minutes,
            can_take=job.status == "open"
            and interview.status in AVAILABLE
            and interview.starts_at <= now < window_end(interview),
            third_eye=str(interview.policy.get("third_eye", "optional")),
            recorded=recorded(interview.policy),
        )
        for interview, job in rows.all()
    ]
