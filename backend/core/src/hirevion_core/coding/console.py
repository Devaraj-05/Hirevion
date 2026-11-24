"""The coding console's server side (SP-16; ADR-0033): the open coding question as the desktop
shows it, the final code when a question ends without a submission, and the console's integrity
events (§48).

Submitting goes through the conductor (`Conductor.submit_code`), because a submission is a turn of
the interview: it closes the question and the AI moves on.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.errors import Conflict, Invalid, NotFound
from hirevion_core.engine.state import AskedQuestion
from hirevion_core.models import (
    CodingSubmission,
    CodingTelemetry,
    Interview,
    InterviewQuestion,
    QuestionVersion,
    WorkspaceSnapshot,
)
from hirevion_core.models.coding import CLIPBOARD_KINDS, CODING_LANGUAGES, TELEMETRY_KINDS

CODE_MAX_BYTES = 256 * 1024
TELEMETRY_BATCH = 200
CHARS_MAX = 10_000_000
CLOCK_SLACK = timedelta(minutes=2)
"""How far an event's time may sit outside the question's time (the desktop's clock, queued
events sent after a reconnect)."""


@dataclass(frozen=True, slots=True)
class Draft:
    language: str | None
    content: str
    saved_at: datetime


@dataclass(frozen=True, slots=True)
class CodingQuestion:
    """What the desktop's console needs: the question, its languages and any starter code."""

    question_id: str
    text: str
    languages: list[str]
    starter_code: dict[str, str]
    time_limit_seconds: int | None
    asked_at: datetime
    draft: Draft | None


@dataclass(frozen=True, slots=True)
class TelemetryEvent:
    kind: str
    occurred_at: datetime
    chars: int | None = None


def offered_languages(languages: Sequence[str]) -> list[str]:
    """The languages the console offers and a submission may use: the question's supported ones,
    else all four (a question whose languages aren't supported must still be answerable)."""
    chosen = [lang for lang in (q.lower() for q in languages) if lang in CODING_LANGUAGES]
    return chosen or list(CODING_LANGUAGES)


def sha256(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


async def _latest_snapshot(session: AsyncSession, question_id: UUID) -> WorkspaceSnapshot | None:
    return await session.scalar(
        select(WorkspaceSnapshot)
        .where(WorkspaceSnapshot.question_id == question_id, WorkspaceSnapshot.kind == "code")
        .order_by(WorkspaceSnapshot.created_at.desc(), WorkspaceSnapshot.id.desc())
        .limit(1)
    )


async def _starter_code(
    session: AsyncSession, question: AskedQuestion, languages: Sequence[str]
) -> dict[str, str]:
    ref = question.source_ref or {}
    if isinstance(ref.get("starter_code"), dict):  # a question the plan wrote (C8-11)
        return {lang: str(code) for lang, code in ref["starter_code"].items() if lang in languages}
    if "question_id" not in ref or "version" not in ref:
        return {}
    version = await session.scalar(
        select(QuestionVersion).where(
            QuestionVersion.question_id == UUID(str(ref["question_id"])),
            QuestionVersion.version == int(ref["version"]),
        )
    )
    starters: dict[str, Any] = ((version.coding if version else None) or {}).get(
        "starter_code"
    ) or {}
    return {lang: str(code) for lang, code in starters.items() if lang in languages}


async def coding_question(
    session: AsyncSession, question: AskedQuestion | None
) -> CodingQuestion | None:
    """The open coding question for the console, or None when the open question isn't one."""
    if question is None or question.kind != "coding":
        return None
    languages = offered_languages(question.languages)
    snapshot = await _latest_snapshot(session, UUID(question.id))
    return CodingQuestion(
        question_id=question.id,
        text=question.text,
        languages=languages,
        starter_code=await _starter_code(session, question, languages),
        time_limit_seconds=question.time_limit_seconds,
        asked_at=question.asked_at,
        draft=Draft(snapshot.language, snapshot.content, snapshot.created_at)
        if snapshot is not None
        else None,
    )


def submission(
    interview: Interview, question_id: UUID, *, language: str, code: str, source: str
) -> CodingSubmission:
    return CodingSubmission(
        organization_id=interview.organization_id,
        interview_id=interview.id,
        question_id=question_id,
        language=language,
        code=code,
        size=len(code.encode("utf-8")),
        sha256=sha256(code),
        source=source,
    )


async def keep_last_text(
    session: AsyncSession, interview: Interview, question_id: UUID, source: str
) -> CodingSubmission | None:
    """A coding question ended without a submission (its time ran out, a spoken answer, the
    interview ending): the last text the console saved becomes its final code."""
    snapshot = await _latest_snapshot(session, question_id)
    if snapshot is None:
        return None
    question = await session.get(InterviewQuestion, question_id)
    offered = list(question.languages) if question is not None else []
    language = (
        snapshot.language
        if snapshot.language in CODING_LANGUAGES
        else next((lang for lang in offered if lang in CODING_LANGUAGES), "python")
    )
    kept = submission(
        interview, question_id, language=language, code=snapshot.content, source=source
    )
    session.add(kept)
    return kept


async def record_telemetry(
    session: AsyncSession,
    interview: Interview,
    question_id: UUID,
    events: Sequence[TelemetryEvent],
    *,
    now: datetime,
) -> int:
    """Stores a batch of the console's events for a coding question of this interview. Only the
    lengths of clipboard events are kept; there is no field for their text."""
    if interview.status not in ("in_progress", "interrupted"):
        raise Conflict("interview-not-in-progress", f"The interview is {interview.status}")
    if len(events) > TELEMETRY_BATCH:
        raise Invalid("too-many-events", f"Send at most {TELEMETRY_BATCH} events at a time")
    question = await session.get(InterviewQuestion, question_id)
    if question is None or question.interview_id != interview.id:
        raise NotFound("question-not-found", "No such question in this interview")
    if question.kind != "coding":
        raise Conflict("not-a-coding-question", "That question isn't a coding question")
    earliest = question.asked_at - CLOCK_SLACK
    latest = now + CLOCK_SLACK
    for event in events:
        if event.kind not in TELEMETRY_KINDS:
            raise Invalid("unknown-event", f"Unknown console event {event.kind!r}", field="kind")
        clipboard = event.kind in CLIPBOARD_KINDS
        if clipboard != (event.chars is not None) or (
            event.chars is not None and not 0 <= event.chars <= CHARS_MAX
        ):
            raise Invalid(
                "invalid-chars",
                "Paste, copy and cut carry a length; other events carry none",
                field="chars",
            )
        if not earliest <= event.occurred_at <= latest:
            raise Invalid(
                "event-out-of-time", "An event's time is outside the question", field="at"
            )
    for event in events:
        session.add(
            CodingTelemetry(
                organization_id=interview.organization_id,
                interview_id=interview.id,
                question_id=question_id,
                kind=event.kind,
                chars=event.chars,
                occurred_at=event.occurred_at,
            )
        )
    await session.flush()
    return len(events)
