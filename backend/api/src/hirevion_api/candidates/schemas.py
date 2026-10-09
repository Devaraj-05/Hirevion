"""Response bodies for resumes, candidates and applications."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

from hirevion_api.jobs.schemas import DocumentStatus

Stage = Literal[
    "uploaded",
    "parsed",
    "screened",
    "ranked",
    "review",
    "shortlisted",
    "rejected",
    "on_hold",
    "interview",
    "interviewed",
]


class CandidateRef(BaseModel):
    id: UUID
    name: str


class ResumeDocumentResponse(BaseModel):
    """A resume or ZIP archive uploaded to a job, and how far the pipeline got with it."""

    id: UUID
    kind: Literal["resume", "archive"]
    status: DocumentStatus
    filename: str | None
    content_type: str | None
    size: int
    error_code: str | None
    attempts: int
    parent_id: UUID | None
    flags: dict[str, Any]
    candidate: CandidateRef | None
    created_at: datetime
    updated_at: datetime


class CandidateSummary(BaseModel):
    id: UUID
    name: str
    email: str | None
    location: str | None
    headline: str | None
    skills: list[str]
    """The first few skills, in the resume's order."""
    flags: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ApplicationResponse(BaseModel):
    id: UUID
    stage: Stage
    document_id: UUID | None
    candidate: CandidateSummary
    created_at: datetime


class CandidateSkillResponse(BaseModel):
    name: str
    skill_id: UUID | None
    years: float | None


class CandidateApplication(BaseModel):
    id: UUID
    job_id: UUID
    job_reference: str
    job_title: str
    stage: Stage
    created_at: datetime


class CandidateDocument(BaseModel):
    id: UUID
    filename: str | None
    content_type: str | None
    size: int
    status: DocumentStatus
    flags: dict[str, Any]
    created_at: datetime


class CandidateResponse(CandidateSummary):
    phone: str | None
    profile: dict[str, Any]
    """The parsed resume: every item carries its `quote`, `page` and `section`."""
    skill_details: list[CandidateSkillResponse]
    applications: list[CandidateApplication]
    documents: list[CandidateDocument]
