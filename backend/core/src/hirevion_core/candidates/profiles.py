"""From a parsed resume to a candidate (PRD §13 "Candidate Profile"): match or create the
candidate, take the latest resume's profile, skills and embedding, and add the application for
the job the resume was uploaded to. Runs in the documents consumer, so its audit entries are the
system's, naming the person who uploaded the resume."""

from __future__ import annotations

from decimal import Decimal
from pathlib import PurePath
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.audit import AuditEntry, AuditService
from hirevion_core.candidates.dedupe import match
from hirevion_core.documents.pii import normalise_phone
from hirevion_core.documents.resume import ResumeResult
from hirevion_core.jobs.taxonomy import resolve_skills
from hirevion_core.models import Application, Candidate, CandidateSkill, Document

_audit = AuditService()
HEADLINE_MAX = 200


def _value(profile: dict[str, Any], name: str) -> str | None:
    item = profile.get(name)
    return str(item["value"]).strip() or None if isinstance(item, dict) else None


def headline(profile: dict[str, Any]) -> str | None:
    """The current or latest role ("Senior Engineer at Acme"), else the summary's start."""
    positions = profile.get("positions") or []
    current = next((p for p in positions if p.get("current")), positions[0] if positions else None)
    if current and (current.get("title") or current.get("company")):
        parts = [current.get("title"), current.get("company")]
        return " at ".join(part for part in parts if part)[:HEADLINE_MAX]
    summary = _value(profile, "summary")
    return summary[:HEADLINE_MAX] if summary else None


async def _replace_skills(
    session: AsyncSession, candidate: Candidate, skills: list[dict[str, Any]]
) -> None:
    await session.execute(delete(CandidateSkill).where(CandidateSkill.candidate_id == candidate.id))
    resolved = await resolve_skills(session, [str(skill["name"]) for skill in skills])
    seen: set[str] = set()
    position = 0
    for skill, known in zip(skills, resolved, strict=True):
        if known is None or known.name.lower() in seen:
            continue
        seen.add(known.name.lower())
        years = skill.get("years")
        session.add(
            CandidateSkill(
                organization_id=candidate.organization_id,
                candidate_id=candidate.id,
                position=position,
                name=known.name,
                skill_id=known.skill_id,
                years=None if years is None else Decimal(str(years)),
            )
        )
        position += 1


async def ensure_application(
    session: AsyncSession, document: Document, candidate: Candidate
) -> None:
    """Links the resume to its candidate, and the candidate to the resume's job."""
    document.candidate_id = candidate.id
    if document.job_id is None:
        return
    application = await session.scalar(
        select(Application).where(
            Application.job_id == document.job_id, Application.candidate_id == candidate.id
        )
    )
    if application is None:
        session.add(
            Application(
                organization_id=document.organization_id,
                candidate_id=candidate.id,
                job_id=document.job_id,
                document_id=document.id,
                stage="parsed",
                created_by=document.created_by,
            )
        )
    else:
        application.document_id = document.id
        if application.stage == "uploaded":
            application.stage = "parsed"


async def build(
    session: AsyncSession,
    document: Document,
    result: ResumeResult,
    *,
    flags: dict[str, Any],
    embedding: list[float] | None,
) -> Candidate:
    profile = result.profile
    email = _value(profile, "email")
    phone = normalise_phone(_value(profile, "phone") or "")
    parsed_name = _value(profile, "name")
    # A name taken from the file's name stands in until the candidate has a real one; it never
    # matches anyone (every "resume.pdf" would be the same person).
    stand_in = PurePath(document.filename or "").stem or "Unnamed candidate"
    found = await match(session, email=email, phone=phone, name=parsed_name)
    candidate_flags = {**flags}
    if found.possible_duplicate_of is not None:
        candidate_flags["possible_duplicate_of"] = str(found.possible_duplicate_of)

    candidate = found.candidate
    action = "candidate.merged" if candidate is not None else "candidate.created"
    if candidate is None:
        candidate = Candidate(
            organization_id=document.organization_id,
            name=parsed_name or stand_in,
            created_by=document.created_by,
        )
        session.add(candidate)
    candidate.name = parsed_name or candidate.name
    candidate.email = email or candidate.email
    candidate.phone = phone or candidate.phone
    candidate.location = _value(profile, "location") or candidate.location
    candidate.headline = headline(profile) or candidate.headline
    candidate.profile = profile
    candidate.flags = candidate_flags
    candidate.embedding = embedding if embedding is not None else candidate.embedding
    candidate.resume_document_id = document.id
    await session.flush()
    await _replace_skills(session, candidate, list(profile.get("skills") or []))

    await ensure_application(session, document, candidate)
    await session.flush()
    await _audit.append(
        session,
        document.organization_id,
        AuditEntry(
            action=action,
            resource_type="candidate",
            resource_id=str(candidate.id),
            details={
                "document_id": str(document.id),
                "job_id": str(document.job_id) if document.job_id else None,
                "matched_by": found.reason,
                "uploaded_by": str(document.created_by) if document.created_by else None,
            },
        ),
    )
    return candidate
