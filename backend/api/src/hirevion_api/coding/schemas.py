"""Bodies and answers of the coding console's routes (`docs/api/contracts/coding.md`)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from hirevion_api.interview_session.schemas import SessionState

Language = Literal["python", "javascript", "typescript", "sql"]
EventKind = Literal["typing_started", "typing_stopped", "paste", "copy", "cut", "focus", "blur"]


class Draft(BaseModel):
    language: str | None
    content: str
    saved_at: datetime


class CodingQuestionBody(BaseModel):
    question_id: UUID
    text: str
    languages: list[Language]
    starter_code: dict[str, str]
    time_limit_seconds: int | None
    asked_at: datetime
    draft: Draft | None
    """The last text the console saved (`POST /workspace`), to restore after a restart."""


class CodingQuestionResponse(BaseModel):
    question: CodingQuestionBody | None
    """None when the open question isn't a coding question."""


class SubmissionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: UUID
    language: Language
    code: str = Field(max_length=300_000)


class Submission(BaseModel):
    id: UUID
    question_id: UUID
    language: Language
    size: int
    sha256: str
    source: Literal["submitted", "time_limit", "closed"]
    submitted_at: datetime


class SubmissionResponse(BaseModel):
    submission: Submission
    state: SessionState
    """In text mode the state already holds the next question; in voice mode the agent asks it."""


class ConsoleEvent(BaseModel):
    """One console event. Paste, copy and cut carry the length of the text, never the text."""

    model_config = ConfigDict(extra="forbid")

    kind: EventKind
    at: AwareDatetime
    chars: int | None = Field(None, ge=0, le=10_000_000)


class TelemetryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: UUID
    events: list[ConsoleEvent] = Field(min_length=1, max_length=200)


class TelemetryResponse(BaseModel):
    accepted: int
