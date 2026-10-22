"""The coding answers (SP-16; PRD §45, §47, §48; ADR-0033): every submission of a coding question
and the integrity events of the text console it was typed in. Nothing here is ever executed.

Both tables are insert-only. A telemetry event carries the length of what was pasted, copied or
cut, never the text, and there are no keystrokes (§48: no unnecessary raw keystroke storage).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from hirevion_core.db.base import Base, IdMixin, TenantMixin

CODING_LANGUAGES = ("python", "javascript", "typescript", "sql")
SUBMISSION_SOURCES = ("submitted", "time_limit", "closed")
"""`submitted`: the candidate pressed Submit. `time_limit`: the question's time ran out and the
last saved text was kept. `closed`: the question ended another way (a spoken answer, the
interview ending) and the last saved text was kept."""
TELEMETRY_KINDS = ("typing_started", "typing_stopped", "paste", "copy", "cut", "focus", "blur")
CLIPBOARD_KINDS = ("paste", "copy", "cut")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _question_fks() -> tuple[ForeignKeyConstraint, ForeignKeyConstraint]:
    return (
        ForeignKeyConstraint(
            ["organization_id", "interview_id"],
            ["interviews.organization_id", "interviews.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "question_id"],
            ["interview_questions.organization_id", "interview_questions.id"],
            ondelete="CASCADE",
        ),
    )


class CodingSubmission(IdMixin, TenantMixin, Base):
    """The code given for a coding question. The latest one is the question's final code."""

    __tablename__ = "coding_submissions"
    __table_args__ = (
        *_question_fks(),
        CheckConstraint(_in("language", CODING_LANGUAGES), name="language"),
        CheckConstraint(_in("source", SUBMISSION_SOURCES), name="source"),
        CheckConstraint("size >= 0", name="size"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256"),
        Index("ix_coding_submissions_interview_id", "interview_id", "created_at"),
    )

    interview_id: Mapped[UUID]
    question_id: Mapped[UUID]
    language: Mapped[str] = mapped_column(Text)
    code: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.clock_timestamp())


class CodingTelemetry(IdMixin, TenantMixin, Base):
    """One integrity event from the coding console (§48), with the time the desktop saw it."""

    __tablename__ = "coding_telemetry"
    __table_args__ = (
        *_question_fks(),
        CheckConstraint(_in("kind", TELEMETRY_KINDS), name="kind"),
        CheckConstraint(
            f"({_in('kind', CLIPBOARD_KINDS)} AND chars IS NOT NULL AND chars >= 0) OR "
            f"(NOT {_in('kind', CLIPBOARD_KINDS)} AND chars IS NULL)",
            name="chars",
        ),
        Index("ix_coding_telemetry_interview_id", "interview_id", "occurred_at"),
    )

    interview_id: Mapped[UUID]
    question_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(Text)
    chars: Mapped[int | None] = mapped_column(Integer)
    """Paste, copy and cut: how many characters; the text itself is never sent."""
    occurred_at: Mapped[datetime]
    received_at: Mapped[datetime] = mapped_column(server_default=func.now())
