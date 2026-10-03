"""Is this resume someone we already have? (ADR-0015)

In order: the same email, the same phone, then a near-identical name (trigram similarity of at
least 0.92) whose candidate has no conflicting email or phone. A similar name with a conflicting
contact is a different person as far as we can tell, but is flagged as a possible duplicate for
a recruiter to look at. A file already parsed (the same SHA-256) is found before any of this, so
it costs no second AI call.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.documents.pii import normalise_phone
from hirevion_core.models import Candidate, Document

NAME_SIMILARITY = 0.92


@dataclass(frozen=True, slots=True)
class Match:
    candidate: Candidate | None
    reason: str | None = None
    """`email`, `phone` or `name`."""
    possible_duplicate_of: UUID | None = None


async def match(
    session: AsyncSession, *, email: str | None, phone: str | None, name: str | None
) -> Match:
    if email:
        found = await session.scalar(select(Candidate).where(Candidate.email == email.strip()))
        if found is not None:
            return Match(found, "email")
    digits = normalise_phone(phone) if phone else None
    if digits:
        found = await session.scalar(
            select(Candidate).where(Candidate.phone == digits).order_by(Candidate.created_at)
        )
        if found is not None:
            return Match(found, "phone")
    if name and name.strip():
        cleaned = " ".join(name.split())
        similarity = func.similarity(Candidate.name, cleaned)
        found = await session.scalar(
            select(Candidate)
            .where(similarity >= NAME_SIMILARITY)
            .order_by(similarity.desc(), Candidate.created_at)
            .limit(1)
        )
        if found is not None:
            conflict = bool(
                (email and found.email and found.email.lower() != email.strip().lower())
                or (digits and found.phone and found.phone != digits)
            )
            return Match(None, possible_duplicate_of=found.id) if conflict else Match(found, "name")
    return Match(None)


async def parsed_copy(session: AsyncSession, sha256: str) -> Document | None:
    """A resume with these exact bytes that was already parsed into a candidate."""
    found: Document | None = await session.scalar(
        select(Document)
        .where(
            Document.sha256 == sha256,
            Document.kind == "resume",
            Document.status == "parsed",
            Document.candidate_id.is_not(None),
        )
        .order_by(Document.created_at)
        .limit(1)
    )
    return found
