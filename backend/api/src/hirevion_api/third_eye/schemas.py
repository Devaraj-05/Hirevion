"""`docs/api/contracts/third-eye.md`'s bodies."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

PairingStatus = Literal["issued", "redeemed", "connected", "disconnected", "revoked", "expired"]


class IssueBody(BaseModel):
    interview_id: UUID


class PairingIssued(BaseModel):
    pairing_id: UUID
    # The phone page's URL; the token is in its fragment, which browsers never send.
    qr_url: str
    expires_at: datetime
    status: PairingStatus


class DeviceInfo(BaseModel):
    platform: str


class VideoInfo(BaseModel):
    width: int
    height: int
    fps: int | None = None


class PairingState(BaseModel):
    pairing_id: UUID
    status: PairingStatus
    expires_at: datetime
    device: DeviceInfo | None
    connected_at: datetime | None
    last_seen_at: datetime | None
    video: VideoInfo | None
    reconnects: int


class PhoneDevice(BaseModel):
    user_agent: str = Field("", max_length=1000)


class RedeemBody(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    device: PhoneDevice = Field(default_factory=lambda: PhoneDevice(user_agent=""))


class RejoinBody(BaseModel):
    device_token: str = Field(min_length=20, max_length=200)


class InterviewNames(BaseModel):
    company: str
    job_title: str


class Placement(BaseModel):
    distance_m: float
    angle: str
    show: list[str]


class JoinResponse(BaseModel):
    pairing_id: UUID
    # Null: connect to the page's own origin, which proxies LiveKit's signalling (`/rtc`).
    livekit_url: str | None
    participant_token: str
    participant_identity: str
    expires_at: datetime
    # Only from `redeem`: the phone keeps it to rejoin after a long lock (`/third-eye/rejoin`).
    device_token: str | None
    interview: InterviewNames
    placement: Placement
