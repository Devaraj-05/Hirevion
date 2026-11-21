"""Bodies and answers of the report routes (SP-17): a report document of blocks, PDF exports, and
the candidate-visible report (PRD §99)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

ReportKind = Literal["interview", "proctoring", "coding", "candidate", "candidate_visible"]
SectionStatus = Literal["populated", "empty", "pending"]


class TextBlock(BaseModel):
    type: Literal["text"]
    text: str
    tone: Literal["normal", "muted"]


class ListBlock(BaseModel):
    type: Literal["list"]
    items: list[str]


class FactRow(BaseModel):
    label: str
    value: str


class FactsBlock(BaseModel):
    type: Literal["facts"]
    rows: list[FactRow]


class TableBlock(BaseModel):
    type: Literal["table"]
    caption: str
    columns: list[str]
    rows: list[list[str]]


class QuoteItem(BaseModel):
    text: str
    source: str


class QuotesBlock(BaseModel):
    type: Literal["quotes"]
    items: list[QuoteItem]


class NoticeBlock(BaseModel):
    type: Literal["notice"]
    tone: Literal["info", "warning"]
    text: str


class CodeBlock(BaseModel):
    type: Literal["code"]
    caption: str
    language: str | None
    text: str


ReportBlock = Annotated[
    TextBlock | ListBlock | FactsBlock | TableBlock | QuotesBlock | NoticeBlock | CodeBlock,
    Field(discriminator="type"),
]


class ReportSection(BaseModel):
    key: str
    title: str
    status: SectionStatus
    note: str | None
    blocks: list[ReportBlock]


class ReportDocument(BaseModel):
    """A report as data: the web view and the PDF both render it."""

    schema_version: int
    kind: ReportKind
    title: str
    subtitle: str
    audience: Literal["internal", "candidate"]
    confidential: bool
    generated_at: datetime
    subject: dict[str, str | None]
    sections: list[ReportSection]


class ExportBody(BaseModel):
    kind: ReportKind
    interview_id: UUID | None = None
    candidate_id: UUID | None = None


class ReportExportResponse(BaseModel):
    id: UUID
    kind: ReportKind
    interview_id: UUID | None
    candidate_id: UUID | None
    bytes: int
    sha256: str
    renderer: str
    requested_by: UUID | None
    requested_by_name: str | None
    created_at: datetime


class ReportExportList(BaseModel):
    items: list[ReportExportResponse]


class CandidateReportItem(BaseModel):
    key: str
    title: str
    text: str
    include: bool
    allowed: bool
    """Whether the organisation lets this item be released at all."""


class ReleasedItem(BaseModel):
    key: str
    title: str
    text: str


class CandidateReportResponse(BaseModel):
    interview_id: UUID
    status: Literal["none", "draft", "released", "withdrawn"]
    ready: bool
    """Whether the interview has ended, so a report can be drafted and released."""
    items: list[CandidateReportItem]
    released: list[ReleasedItem]
    approved_by: UUID | None
    approved_by_name: str | None
    approved_at: datetime | None
    withdrawn_at: datetime | None
    withdrawn_reason: str | None


class DraftItem(BaseModel):
    text: str = Field(max_length=4000)
    include: bool


class CandidateReportBody(BaseModel):
    items: dict[str, DraftItem]


class WithdrawBody(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class CandidateReportSettings(BaseModel):
    """Which of the five items recruiters may release, by key."""

    items: dict[str, bool]


class PortalReportItem(BaseModel):
    interview_id: UUID
    reference: str
    job_title: str
    released_at: datetime | None
    items: list[ReleasedItem]


class PortalReportList(BaseModel):
    reports: list[PortalReportItem]


def document_of(raw: dict[str, Any]) -> ReportDocument:
    return ReportDocument.model_validate(raw)


# One interview's analytics for the recruiter's dashboard (C8-7, ADR-0047).


class AnalyticsQuestion(BaseModel):
    id: UUID
    position: int
    kind: str
    skill: str | None
    difficulty: str | None
    text: str
    status: str
    asked_ms: int | None
    """When the interviewer began it, from the interview's start."""
    thinking_ms: int | None
    """From the end of the question to the start of the answer; null without an answer."""
    speaking_ms: int
    words: int
    quality: str | None
    """The live analysis's verdict (strong, partial, weak, no_answer)."""
    score: float | None
    """The evaluation's score out of 10 (a reviewer's change included); null until evaluated."""


class AnalyticsSkill(BaseModel):
    skill: str
    required: bool
    covered: bool
    asked: int
    answered: int
    planned: int
    dropped: bool
    score: float | None


class AnalyticsSpeech(BaseModel):
    """PRD §59's measures: signals for a reviewer, never proof (§57)."""

    candidate_ms: int
    ai_ms: int
    words: int
    words_per_minute: int | None
    median_response_ms: int | None
    long_pauses: int
    """Answers that began more than 10 seconds after the question."""
    fillers: dict[str, int]
    fillers_per_100_words: float | None
    candidate_share: float | None
    pace_unreliable: bool
    """The stored speech times give an impossible pace (over 300 words a minute), so
    `words_per_minute` is null: answers stored before 2026-11-21's agent fix kept only their last
    stretch of speech."""


class AnalyticsEvent(BaseModel):
    id: UUID
    event: str
    severity: Literal["INFO", "WARNING", "CRITICAL"]
    source: str
    offset_ms: int | None
    duration_ms: int | None
    review: str | None
    """A reviewer's outcome: confirmed, false_positive or not_relevant."""


class AnalyticsProcess(BaseModel):
    name: str
    path: str | None = None
    publisher: str | None = None
    window_titles: list[str] = Field(default_factory=list)


class AnalyticsInventory(BaseModel):
    offset_ms: int | None
    count: int | None
    windows: list[str]
    processes: list[AnalyticsProcess]


class AnalyticsIntegrity(BaseModel):
    counts: dict[str, int]
    """Events by severity, leaving out those a reviewer dismissed."""
    events: list[AnalyticsEvent]
    inventory: AnalyticsInventory | None


class InterviewAnalytics(BaseModel):
    interview_id: UUID
    status: str
    planned_minutes: int
    started_at: datetime | None
    ended_at: datetime | None
    duration_ms: int | None
    overall: float | None
    communication: float | None
    questions: list[AnalyticsQuestion]
    skills: list[AnalyticsSkill]
    speech: AnalyticsSpeech
    integrity: AnalyticsIntegrity | None
    """Null for a viewer who may not see proctoring."""
