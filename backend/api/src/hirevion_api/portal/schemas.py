"""Request and response bodies of `/api/v1/portal/*` and `/api/v1/candidate-requests`."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from hirevion_core.candidate_portal.requests import MESSAGE_MAX

RequestKind = Literal[
    "reschedule",
    "support",
    "accommodation",
    "alternative_process",
    "data_access",
    "data_correction",
    "data_erasure",
    "grievance",
    "nomination",
    "consent_withdrawal",
]
RequestStatus = Literal["open", "in_progress", "resolved", "declined"]


class PortalAccount(BaseModel):
    id: UUID
    name: str
    email: str
    locale: str


class PortalOrganization(BaseModel):
    id: UUID
    name: str
    support_email: str = Field(description="Where the candidate writes for help (PRD §25).")


class PortalSessionResponse(BaseModel):
    """Who is signed in to the portal."""

    account: PortalAccount
    organization: PortalOrganization


class PortalInterviewItem(BaseModel):
    id: UUID
    reference: str = Field(description="IV-0042.")
    job_title: str
    status: str
    starts_at: datetime
    expires_at: datetime
    timezone: str = Field(description="The interview's IANA time zone.")
    duration_minutes: int
    can_take: bool = Field(description="Its window is open and it can be started in the app now.")
    third_eye: str
    recorded: str = Field(description="What the interview records, in words.")


class PortalInterviewList(BaseModel):
    now: datetime = Field(description="The server's clock, for countdowns.")
    interviews: list[PortalInterviewItem]


class PortalRequestCreate(BaseModel):
    kind: RequestKind
    message: str = Field("", max_length=MESSAGE_MAX)
    interview_id: UUID | None = None
    details: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Per kind: reschedule `preferred`; accommodation `kinds`; consent withdrawal "
            "`purposes`; nomination `nominee_name`, `nominee_email`, `relationship`; "
            "correction `field`."
        ),
    )


class PortalRequestItem(BaseModel):
    id: UUID
    reference: str = Field(description="RQ-1A2B3C4D.")
    kind: RequestKind
    status: RequestStatus
    message: str
    interview_id: UUID | None
    details: dict[str, Any]
    response: str | None
    created_at: datetime
    updated_at: datetime


class PolicyItem(BaseModel):
    key: str
    title: str
    body: str = Field(description="Markdown, without the title.")


class NoticesResponse(BaseModel):
    """PRD §83: what an interview may collect, and the six policies."""

    disclosures: list[str]
    policies: list[PolicyItem]


class DownloadRelease(BaseModel):
    arch: str
    version: str
    notes: str
    published_at: datetime | None


class DownloadsResponse(BaseModel):
    download_url: str = Field(description="The stable channel's download page; empty until set.")
    minimum_version: str
    releases: list[DownloadRelease]
    system_requirements: list[str]


class CandidateRequestItem(BaseModel):
    """A candidate's request, as recruiters see it."""

    id: UUID
    reference: str
    kind: RequestKind
    status: RequestStatus
    message: str
    details: dict[str, Any]
    response: str | None
    candidate_id: UUID
    candidate_name: str
    candidate_email: str | None
    interview_id: UUID | None
    interview_reference: str | None
    handled_by: UUID | None
    handled_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CandidateRequestUpdate(BaseModel):
    status: Literal["in_progress", "resolved", "declined"]
    response: str | None = Field(None, max_length=MESSAGE_MAX)
