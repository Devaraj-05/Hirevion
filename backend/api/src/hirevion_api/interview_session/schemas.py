"""Bodies and answers of the interview-session routes (`docs/api/contracts/interview-session.md`)
and of the recruiter's views of an interview's transcript, accommodations and briefing."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

CheckStatus = Literal["pass", "warn", "fail", "skipped"]
AnswerMode = Literal["voice", "text"]
Voice = Literal["listening", "thinking", "speaking", "waiting", "paused", "ended", "error"]
WorkspaceKind = Literal["none", "code", "whiteboard"]


# Before the interview


class NoticeItem(BaseModel):
    purpose: str
    text: str
    required: bool


class Notice(BaseModel):
    version: str
    items: list[NoticeItem]


class AccommodationsSummary(BaseModel):
    requested: list[str]
    approved: list[str]


class BriefingResponse(BaseModel):
    instructions: list[str]
    mandatory_checks: list[str]
    notice: Notice
    accommodations: AccommodationsSummary
    answer_mode: AnswerMode
    third_eye: Literal["off", "optional", "required"]
    duration_minutes: int
    support_email: str | None = None


class CheckItem(BaseModel):
    check: str = Field(max_length=40)
    status: CheckStatus
    value: str | None = Field(None, max_length=500)
    detail: str | None = Field(None, max_length=500)


class SystemCheckBody(BaseModel):
    app_version: str = Field(max_length=40)
    os: str = Field(max_length=200)
    results: list[CheckItem] = Field(max_length=30)


class SystemCheckResponse(BaseModel):
    id: UUID
    passed: bool
    failed_mandatory: list[str]


class ConsentItem(BaseModel):
    purpose: str = Field(max_length=40)
    accepted: bool


class ConsentBody(BaseModel):
    notice_version: str = Field(max_length=20)
    items: list[ConsentItem] = Field(max_length=20)


class ConsentResponse(BaseModel):
    id: UUID
    complete: bool
    missing: list[str]


class AccommodationBody(BaseModel):
    kinds: list[str] = Field(min_length=1, max_length=6)
    note: str | None = Field(None, max_length=2000)


class AccommodationCreated(BaseModel):
    id: UUID
    status: Literal["requested", "approved", "declined"]


# The interview


class StartBody(BaseModel):
    system_check_id: UUID
    consent_id: UUID


class QuestionState(BaseModel):
    id: UUID
    index: int
    text: str
    type: str
    time_limit_seconds: int | None
    workspace: WorkspaceKind
    languages: list[str]


class SessionState(BaseModel):
    status: str
    started_at: datetime | None
    deadline_at: datetime | None
    remaining_seconds: int
    third_eye: Literal["off", "optional", "required"]
    workspace: WorkspaceKind
    answer_mode: AnswerMode
    question: QuestionState | None = Field(
        None, description="The open question; in text mode always the next one to answer."
    )
    voice: Voice
    stage: str = Field(description="PRD §35's stage.")
    message: str | None = Field(
        None, description="What the AI said last (its acknowledgement and the question)."
    )
    notice: dict[str, Any] | None = None


class StartResponse(BaseModel):
    livekit_url: str
    room: str
    participant_identity: str
    participant_token: str
    token_expires_at: datetime
    state: SessionState


class StateResponse(BaseModel):
    state: SessionState


class AnswerBody(BaseModel):
    question_id: UUID
    text: str = Field(max_length=20_000)


class WorkspaceBody(BaseModel):
    question_id: UUID
    kind: Literal["code", "whiteboard"]
    language: str | None = Field(None, max_length=20)
    content: str = Field(max_length=300_000)


class CompleteBody(BaseModel):
    reason: Literal["finished", "candidate_ended"]


class CompleteResponse(BaseModel):
    status: str


# The recruiter's views


class TranscriptSegmentResponse(BaseModel):
    seq: int
    speaker: Literal["ai", "candidate"]
    text: str
    start_ms: int
    end_ms: int
    question_id: UUID | None
    confidence: float | None


class AnswerResponse(BaseModel):
    mode: AnswerMode
    text: str
    late: bool
    flags: list[str]
    created_at: datetime


class TranscriptQuestion(BaseModel):
    id: UUID
    position: int
    kind: str
    stage: str
    skill: str | None
    difficulty: str | None
    type: str | None
    text: str
    source: str
    source_ref: dict[str, Any] = Field(description="Where it came from (PRD §36).")
    parent_id: UUID | None
    status: str
    asked_at: datetime
    answers: list[AnswerResponse]


class CoverageItem(BaseModel):
    skill: str
    required: bool
    covered: bool
    asked: int
    answered: int
    planned: int


class ArtifactLink(BaseModel):
    kind: Literal["json", "vtt", "txt"]
    url: str
    bytes: int
    sha256: str


class TranscriptResponse(BaseModel):
    interview_id: UUID
    status: str
    stage: str | None
    transcript_status: Literal["none", "pending", "ready", "failed"]
    coverage: list[CoverageItem]
    questions: list[TranscriptQuestion]
    segments: list[TranscriptSegmentResponse]
    artifacts: list[ArtifactLink]


class AccommodationResponse(BaseModel):
    id: UUID
    kinds: list[str]
    note: str
    status: Literal["requested", "approved", "declined"]
    approved_kinds: list[str]
    decision_note: str | None
    decided_by: UUID | None
    decided_at: datetime | None
    created_at: datetime


class AccommodationDecision(BaseModel):
    approved: list[str] = Field(
        max_length=6, description="The kinds to approve; none declines the request."
    )
    note: str | None = Field(None, max_length=2000)


class FaqItem(BaseModel):
    question: str = Field(min_length=3, max_length=300)
    answer: str = Field(min_length=1, max_length=2000)


class InterviewBriefingSettings(BaseModel):
    instructions: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="What candidates are told before the interview; empty uses the defaults.",
    )
    faq: list[FaqItem] = Field(
        default_factory=list,
        max_length=50,
        description="The only source the AI answers candidates' final questions from.",
    )
