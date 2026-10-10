"""Bodies and answers of the recording routes: the desktop's (`docs/api/contracts/recordings.md`)
and the recruiter's playback listing."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, StringConstraints

from hirevion_core.recordings.tracks import MAX_SEQ, TRACK_PATTERN

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$", to_lower=True)]


class SegmentBody(BaseModel):
    interview_id: UUID
    track: str = Field(pattern=f"^({TRACK_PATTERN})$")
    seq: int = Field(ge=0, le=MAX_SEQ)
    started_at: AwareDatetime
    # The limits (50,000,000 bytes, 60,000 ms) are the service's, which answers them with the
    # contract's own codes (`413 segment-too-large`, `422 segment-too-long`).
    duration_ms: int = Field(ge=1)
    bytes: int = Field(ge=1)
    sha256: Sha256
    container: Literal["mp4", "webm"]
    codec: Literal["h264", "vp8", "opus", "aac"]


class UploadResponse(BaseModel):
    segment_id: UUID
    upload_url: str
    expires_at: datetime
    headers: dict[str, str]


class AckBody(BaseModel):
    sha256: Sha256


class AckResponse(BaseModel):
    status: Literal["acknowledged"]


class TrackProgress(BaseModel):
    acknowledged_through: int | None
    missing: list[int]


class RecoveryResponse(BaseModel):
    tracks: dict[str, TrackProgress]


# The recruiter's playback


class GapItem(BaseModel):
    from_seq: int
    to_seq: int
    from_time: datetime | None
    to_time: datetime | None
    reason: Literal["missing", "corrupt"]


class PlaybackFile(BaseModel):
    url: str
    container: Literal["mp4", "webm"]
    bytes: int
    sha256: str
    duration_ms: int


class PlaybackSegment(BaseModel):
    seq: int
    started_at: datetime
    duration_ms: int
    url: str


class PlaybackTrack(BaseModel):
    track: str
    status: Literal["recording", "assembly-pending", "assembling", "assembled", "failed"]
    stalled: bool
    first_seq: int | None
    last_seq: int | None
    gaps: list[GapItem]
    file: PlaybackFile | None
    timeline_url: str | None
    # The acknowledged segments, until the track is assembled into `file`.
    segments: list[PlaybackSegment]


class PlaybackResponse(BaseModel):
    interview_id: UUID
    # Every URL is read-only and stops working at this time.
    expires_at: datetime
    tracks: list[PlaybackTrack]
