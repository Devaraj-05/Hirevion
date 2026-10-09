"""Bodies of the desktop's sign-in routes, exactly as `candidate-auth.md` writes them."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AppBody(BaseModel):
    version: str = Field(max_length=40)
    channel: Literal["stable", "beta"] = "stable"
    os: str = Field("", max_length=100)
    arch: Literal["x64", "arm64"] = "x64"


class DeviceBody(BaseModel):
    name: str = Field("", max_length=100)


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=254)
    password: str = Field(max_length=1024)
    app: AppBody
    device: DeviceBody = Field(default_factory=lambda: DeviceBody(name=""))


class CandidateBody(BaseModel):
    id: UUID
    name: str
    email: str
    locale: str


class OrganizationBody(BaseModel):
    id: UUID
    name: str
    support_email: str


class CandidateInterview(BaseModel):
    id: UUID
    job_title: str
    status: Literal["invited", "in_progress", "interrupted"]
    starts_at: datetime
    expires_at: datetime
    duration_minutes: int
    third_eye: Literal["off", "optional", "required"]
    proctoring_level: Literal["off", "basic", "standard", "strict"]
    coding: bool


class SignedInResponse(BaseModel):
    status: Literal["ok"] = "ok"
    access_token: str
    token_type: Literal["DPoP"] = "DPoP"  # noqa: S105 (the token kind, not a secret)
    expires_in: int
    refresh_token: str
    refresh_expires_in: int
    candidate: CandidateBody
    organization: OrganizationBody
    interviews: list[CandidateInterview]


class OtpRequiredResponse(BaseModel):
    status: Literal["otp_required"] = "otp_required"
    challenge_id: UUID
    sent_to: str
    expires_in: int


class OtpVerifyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_id: UUID
    code: str = Field(min_length=1, max_length=12)


class OtpResendBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_id: UUID


class RefreshBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(max_length=200)


class RefreshedResponse(BaseModel):
    access_token: str
    token_type: Literal["DPoP"] = "DPoP"  # noqa: S105 (the token kind, not a secret)
    expires_in: int
    refresh_token: str
    refresh_expires_in: int


class ProfileResponse(BaseModel):
    candidate: CandidateBody
    organization: OrganizationBody
    interviews: list[CandidateInterview]


class SessionInterview(BaseModel):
    id: UUID
    status: Literal["invited", "in_progress", "interrupted"]
    starts_at: datetime
    expires_at: datetime
    duration_minutes: int


class SessionTokenResponse(BaseModel):
    session_token: str
    token_type: Literal["DPoP"] = "DPoP"  # noqa: S105 (the token kind, not a secret)
    expires_at: datetime
    interview: SessionInterview


class ReleaseLatest(BaseModel):
    version: str
    notes: str
    published_at: datetime | None


class ReleaseCheckResponse(BaseModel):
    status: Literal["ok", "update-available", "update-required"]
    latest: ReleaseLatest | None
    minimum_version: str
    download_url: str
