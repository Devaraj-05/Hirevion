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
