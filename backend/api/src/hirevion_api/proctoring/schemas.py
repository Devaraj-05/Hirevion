"""Request and response shapes of the proctoring routes: the desktop's (`proctoring.md`) and the
recruiter's report, live view, evidence and reviews."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["INFO", "WARNING", "CRITICAL"]
ReviewStatus = Literal["pending", "confirmed", "false_positive", "not_relevant"]
ReviewOutcome = Literal["confirmed", "false_positive", "not_relevant"]
MatchKind = Literal["name", "path", "publisher", "signature", "hash", "window_title"]
Channel = Literal["up", "down", "unknown"]


# The desktop.


class SessionBody(BaseModel):
    interview_id: UUID
    app_version: str = Field(max_length=40)


class Threshold(BaseModel):
    warn_after_ms: int | None = None
    critical_after_ms: int | None = None


class RuleCondition(BaseModel):
    match: MatchKind
    value: str


class AppRule(BaseModel):
    """One application rule. A blocking `name` rule always carries `with`; a name alone never
    blocks (PRD §61)."""

    model_config = ConfigDict(populate_by_name=True)

    match: MatchKind
    value: str
    category: str | None = None
    with_: list[RuleCondition] = Field(default_factory=list, alias="with")


class AppRules(BaseModel):
    blocked: list[AppRule]
    allowed: list[AppRule]


class SessionResponse(BaseModel):
    proctor_session_id: UUID
    policy_version: int
    level: Literal["off", "basic", "standard", "strict"]
    checks: list[str]
    thresholds: dict[str, Threshold]
    app_rules: AppRules
    single_display: bool
    heartbeat_seconds: int
    batch_max_events: int
    accommodations: list[str]
    acked_through: int = Field(
        description="The highest sequence number below which everything has arrived; a client "
        "that lost its queue continues after it."
    )


class EvidenceRef(BaseModel):
    type: str = Field(max_length=40)
    blob_path: str = Field(max_length=400)


class EventBody(BaseModel):
    seq: int = Field(ge=1)
    event: str = Field(max_length=60)
    source: str = Field(max_length=30)
    started_at: datetime
    duration_ms: int | None = None
    confidence: float | None = 1.0
    evidence: list[EvidenceRef] = Field(default_factory=list, max_length=20)
    details: dict[str, Any] = Field(default_factory=dict)


class EventsBody(BaseModel):
    proctor_session_id: UUID
    events: list[EventBody] = Field(min_length=1, max_length=500)


class EventsAck(BaseModel):
    acked_through: int
    missing: list[int]


class HeartbeatBody(BaseModel):
    proctor_session_id: UUID
    seq_high: int = Field(ge=0)
    camera: str = Field(max_length=20)
    mic: str = Field(max_length=20)
    screen: str = Field(max_length=20)
    third_eye: str = Field("not_required", max_length=20)
    displays: int = Field(1, ge=0, le=64)
    cpu_percent: float | None = Field(None, ge=0, le=1000)
    vision_fps: float | None = Field(None, ge=0, le=1000)


class HeartbeatAck(BaseModel):
    server_time: datetime
    missing: list[int]


class EvidenceUploadBody(BaseModel):
    proctor_session_id: UUID
    kind: Literal["screen", "camera"]
    seq: int = Field(ge=1)
    content_type: str = Field(max_length=60)
    bytes: int = Field(ge=1)
    sha256: str = Field(min_length=64, max_length=64)


class EvidenceUploadResponse(BaseModel):
    upload_url: str
    blob_path: str
    headers: dict[str, str]


# The recruiter.


class ReviewInfo(BaseModel):
    outcome: ReviewOutcome
    reason: str
    reviewer_id: UUID
    reviewed_at: datetime


class ProctorEventItem(BaseModel):
    """An event as PRD §67 describes it, with the server's severity and the review."""

    id: UUID
    seq: int | None
    event: str
    source: str
    origin: Literal["client", "server"]
    severity: Severity
    started_at: datetime
    duration_ms: int | None
    ongoing: bool
    phase: Literal["started", "escalated", "ended"] | None
    confidence: float | None
    details: dict[str, Any]
    review_status: ReviewStatus
    policy_version: int
    evidence_count: int = 0
    review: ReviewInfo | None = None


class Devices(BaseModel):
    camera: Channel
    mic: Channel
    screen: Channel
    third_eye: Channel


class Connection(BaseModel):
    state: Literal["ok", "gap", "interrupted", "closed"]
    last_heartbeat_at: datetime | None


class ProctoringStatus(BaseModel):
    """The devices and the connection, as the server sees them."""

    session: Literal["open", "closed"]
    devices: Devices
    connection: Connection
    displays: int | None
    cpu_percent: float | None
    vision_fps: float | None
    reported: dict[str, str | None]


class Counts(BaseModel):
    total: int
    by_severity: dict[str, int]
    by_review: dict[str, int]
    dismissed: int
    open_alerts: int


class SessionSummary(BaseModel):
    id: UUID
    status: Literal["open", "closed"]
    level: str
    policy_version: int
    opened_at: datetime
    closed_at: datetime | None
    acked_through: int
    heartbeats: int
    last_heartbeat_at: datetime | None
    checks: list[str]
    accommodations: list[str]
    app_version: str


class ProctoringReport(BaseModel):
    """What PRD §68's proctoring report is built from: every event, dismissed ones included."""

    interview_id: UUID
    session: SessionSummary | None
    status: ProctoringStatus | None
    counts: Counts
    events: list[ProctorEventItem]
    next_cursor: str | None


class LiveInterview(BaseModel):
    status: str
    started_at: datetime | None
    deadline_at: datetime | None
    duration_minutes: int


class LiveAi(BaseModel):
    voice: str | None
    agent_connected: bool


class TranscriptTailItem(BaseModel):
    seq: int
    speaker: Literal["ai", "candidate"]
    text: str
    start_ms: int


class LiveSnapshot(BaseModel):
    """The dashboard's starting point (PRD §66); follow `/ws/proctoring/{id}?after=cursor`."""

    interview: LiveInterview
    proctoring: ProctoringStatus | None
    ai: LiveAi
    counts: Counts
    events: list[ProctorEventItem]
    transcript: list[TranscriptTailItem]
    cursor: str


class EvidenceItem(BaseModel):
    id: UUID
    event_id: UUID | None
    kind: str
    origin: Literal["client", "server"]
    url: str | None = Field(description="A five-minute download link; empty for references.")
    content_type: str | None
    bytes: int | None
    sha256: str | None
    window_start: datetime | None
    window_end: datetime | None
    ref: dict[str, Any]
    created_at: datetime


class EvidenceList(BaseModel):
    items: list[EvidenceItem]


class ReviewBody(BaseModel):
    outcome: ReviewOutcome
    reason: str = Field(min_length=1, max_length=1000)


class ObserveResponse(BaseModel):
    """A hidden, subscribe-only LiveKit token to watch the candidate's camera, screen and
    third eye."""

    livekit_url: str
    room: str
    identity: str
    token: str
    expires_at: datetime
