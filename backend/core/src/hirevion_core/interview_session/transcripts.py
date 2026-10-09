"""The two-sided transcript (PRD §41, §43, §85): segments as the interview happens, and its JSON,
VTT and TXT artifacts once it has ended.

Each segment has its speaker, text, start and end (milliseconds from the interview's start), the
question it belongs to and, for speech, the recogniser's confidence. The AI's segments are timed
from when the turn was decided, with the length estimated from the text; the agent's own timing
replaces that estimate when it reports one. A consumer of `interview.completed` writes the
artifacts to `{organization}/interviews/{id}/transcript/` and records them, with their SHA-256,
in `transcripts`.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.db.session import Database
from hirevion_core.documents.intake import BlobStore
from hirevion_core.engine.state import InterviewState
from hirevion_core.models import (
    Interview,
    InterviewAnswer,
    InterviewQuestion,
    InterviewSession,
    Transcript,
    TranscriptSegment,
)
from hirevion_core.storage.paths import interview_blob

log = logging.getLogger(__name__)

CHARS_PER_SECOND = 15
MIN_SPEECH_MS = 600
TOPIC = "interview.completed"
ABANDONED_TOPIC = "interview.abandoned"
ARTIFACTS = {
    "json": ("transcript.json", "application/json"),
    "vtt": ("transcript.vtt", "text/vtt"),
    "txt": ("transcript.txt", "text/plain; charset=utf-8"),
}
SPEAKER_LABELS = {"ai": "AI", "candidate": "Candidate"}


def speech_ms(text: str) -> int:
    return max(MIN_SPEECH_MS, round(len(text) * 1000 / CHARS_PER_SECOND))


def segment(
    state: InterviewState,
    speaker: str,
    text: str,
    *,
    start: datetime,
    end: datetime | None = None,
    question_id: str | None,
    confidence: float | None = None,
) -> TranscriptSegment:
    """The next segment, numbered from the state's counter."""
    state.segment_seq += 1
    start_ms = state.clock.offset_ms(start)
    end_ms = state.clock.offset_ms(end) if end is not None else start_ms + speech_ms(text)
    return TranscriptSegment(
        occurred_at=start,
        organization_id=UUID(state.organization_id),
        interview_id=UUID(state.interview_id),
        seq=state.segment_seq,
        speaker=speaker,
        text=text,
        start_ms=start_ms,
        end_ms=max(start_ms, end_ms),
        question_id=UUID(question_id) if question_id else None,
        confidence=Decimal(f"{min(1.0, max(0.0, confidence)):.3f}")
        if confidence is not None
        else None,
    )


async def segments(session: AsyncSession, interview_id: UUID) -> list[TranscriptSegment]:
    rows = await session.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.interview_id == interview_id)
        .order_by(TranscriptSegment.seq, TranscriptSegment.occurred_at)
    )
    return list(rows.all())


def _timestamp(ms: int, separator: str = ".") -> str:
    hours, rest = divmod(ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{millis:03d}"


def render_vtt(rows: Sequence[TranscriptSegment]) -> str:
    cues = ["WEBVTT", ""]
    for index, row in enumerate(rows, start=1):
        speaker = SPEAKER_LABELS.get(row.speaker, row.speaker)
        text = " ".join(row.text.split()).replace("-->", "->")
        cues += [
            str(index),
            f"{_timestamp(row.start_ms)} --> {_timestamp(max(row.end_ms, row.start_ms + 1))}",
            f"<v {speaker}>{text}",
            "",
        ]
    return "\n".join(cues)


def render_txt(rows: Sequence[TranscriptSegment]) -> str:
    """PRD §43's form: each turn under its speaker, in order."""
    blocks = []
    for row in rows:
        stamp = _timestamp(row.start_ms)[:8]
        blocks.append(f"[{stamp}] {SPEAKER_LABELS.get(row.speaker, row.speaker)}:\n{row.text}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def render_json(
    interview: Interview,
    questions: Sequence[InterviewQuestion],
    answers: Sequence[InterviewAnswer],
    rows: Sequence[TranscriptSegment],
    summary: dict[str, Any],
) -> str:
    by_question: dict[UUID, list[InterviewAnswer]] = {}
    for answer in answers:
        by_question.setdefault(answer.question_id, []).append(answer)
    document = {
        "interview_id": str(interview.id),
        "status": interview.status,
        "started_at": interview.started_at.isoformat() if interview.started_at else None,
        "ended_at": interview.ended_at.isoformat() if interview.ended_at else None,
        "summary": summary,
        "questions": [
            {
                "id": str(q.id),
                "position": q.position,
                "kind": q.kind,
                "stage": q.stage,
                "skill": q.skill,
                "difficulty": q.difficulty,
                "text": q.text,
                "source": q.source,
                "source_ref": q.source_ref,
                "parent_id": str(q.parent_id) if q.parent_id else None,
                "status": q.status,
                "answers": [
                    {"mode": a.mode, "text": a.text, "late": a.late, "flags": list(a.flags)}
                    for a in by_question.get(q.id, [])
                ],
            }
            for q in questions
        ],
        "segments": [
            {
                "seq": row.seq,
                "speaker": row.speaker,
                "text": row.text,
                "start_ms": row.start_ms,
                "end_ms": row.end_ms,
                "question_id": str(row.question_id) if row.question_id else None,
                "confidence": float(row.confidence) if row.confidence is not None else None,
            }
            for row in rows
        ],
    }
    return json.dumps(document, ensure_ascii=False, indent=2)


async def write_artifacts(
    db: Database, storage: BlobStore, organization_id: UUID, interview_id: UUID
) -> Transcript:
    """Renders and stores the three artifacts, and records them; safe to run again."""
    from hirevion_core.engine.completion import CompletionEvaluator

    async with db.tenant(organization_id) as session:
        interview = await session.get_one(Interview, interview_id)
        questions = list(
            (
                await session.scalars(
                    select(InterviewQuestion)
                    .where(InterviewQuestion.interview_id == interview_id)
                    .order_by(InterviewQuestion.position)
                )
            ).all()
        )
        answers = list(
            (
                await session.scalars(
                    select(InterviewAnswer)
                    .where(InterviewAnswer.interview_id == interview_id)
                    .order_by(InterviewAnswer.created_at)
                )
            ).all()
        )
        rows = await segments(session, interview_id)
        row = await session.get(InterviewSession, interview_id)
        summary: dict[str, Any] = {}
        if row is not None and row.state:
            summary = CompletionEvaluator().summary(InterviewState.from_json(row.state))
    rendered = {
        "json": render_json(interview, questions, answers, rows, summary),
        "vtt": render_vtt(rows),
        "txt": render_txt(rows),
    }
    artifacts: dict[str, Any] = {}
    for kind, (filename, content_type) in ARTIFACTS.items():
        data = rendered[kind].encode("utf-8")
        path = interview_blob(organization_id, interview_id, "transcript", filename)
        await storage.put(path, data, content_type)
        artifacts[kind] = {
            "path": str(path),
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "content_type": content_type,
        }
    async with db.tenant(organization_id) as session:
        transcript = await session.get(Transcript, interview_id)
        if transcript is None:
            transcript = Transcript(organization_id=organization_id, interview_id=interview_id)
            session.add(transcript)
        transcript.status = "ready"
        transcript.segment_count = len(rows)
        transcript.artifacts = {**artifacts, "written_at": datetime.now(UTC).isoformat()}
        await session.flush()
    return transcript


async def handle_completed(
    db: Database, storage: BlobStore | None, organization_id: UUID, payload: dict[str, Any]
) -> None:
    """The `interview.completed` and `interview.abandoned` consumers: write the artifacts."""
    if storage is None:
        raise RuntimeError("no blob storage is configured (AZURE_STORAGE_*)")
    await write_artifacts(db, storage, organization_id, UUID(str(payload["interview_id"])))
