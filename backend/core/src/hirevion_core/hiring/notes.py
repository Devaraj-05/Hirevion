"""Notes on a candidate (PRD §71 "add notes"): internal, insert-only, and on an interview's moment
when taken in the review workspace. The candidate portal never reads them."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.actor import Actor
from hirevion_core.access.audit import record
from hirevion_core.access.errors import Invalid
from hirevion_core.models import CandidateNote, Interview
from hirevion_core.models.reporting import NOTE_MAX

LIST_LIMIT = 200


async def add_note(
    session: AsyncSession,
    actor: Actor,
    *,
    candidate_id: UUID,
    body: str,
    interview: Interview | None = None,
    at_ms: int | None = None,
) -> CandidateNote:
    text = body.strip()
    if not text or len(text) > NOTE_MAX:
        raise Invalid("invalid-note", f"Write a note of 1 to {NOTE_MAX} characters", field="body")
    if at_ms is not None and (at_ms < 0 or interview is None):
        raise Invalid("invalid-moment", "A moment needs an interview and can't be negative")
    if interview is not None and interview.candidate_id != candidate_id:
        raise Invalid("invalid-interview", "That interview belongs to another candidate")
    row = CandidateNote(
        organization_id=actor.organization_id,
        candidate_id=candidate_id,
        application_id=interview.application_id if interview is not None else None,
        interview_id=interview.id if interview is not None else None,
        author_id=actor.user_id,
        body=text,
        at_ms=at_ms,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    await record(
        session,
        actor,
        "candidate.note_added",
        "candidate",
        candidate_id,
        details={
            "interview_id": str(interview.id) if interview is not None else None,
            "at_ms": at_ms,
        },
    )
    return row


async def list_notes(
    session: AsyncSession, candidate_id: UUID, *, interview_id: UUID | None = None
) -> list[CandidateNote]:
    """Newest first; for one interview when `interview_id` is given."""
    statement = select(CandidateNote).where(CandidateNote.candidate_id == candidate_id)
    if interview_id is not None:
        statement = statement.where(CandidateNote.interview_id == interview_id)
    rows = await session.scalars(
        statement.order_by(CandidateNote.created_at.desc(), CandidateNote.id.desc()).limit(
            LIST_LIMIT
        )
    )
    return list(rows.all())
