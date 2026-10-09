"""The interview's state (PRD §34): the twelve fields the orchestrator decides from, plus the
stage (§35), the question pool and the clock. It is saved as the checkpoint after every turn
(`interview_sessions.state`) and loaded again by whichever process takes the next turn, so it
round-trips through JSON and holds nothing that can't be rebuilt from it."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

Stage = Literal[
    "start",
    "introduction",
    "easy",
    "medium",
    "hard",
    "follow_up",
    "coding",
    "final_questions",
    "completion",
    "evaluation",
]
STAGES: tuple[str, ...] = get_args(Stage)
Difficulty = Literal["easy", "medium", "hard"]
RUNGS: tuple[str, ...] = get_args(Difficulty)
Quality = Literal["strong", "partial", "weak", "no_answer"]
QuestionKind = Literal["introduction", "main", "follow_up", "coding", "final"]
Source = Literal["pinned", "library", "generated", "resume", "follow_up", "faq", "system"]
AnswerMode = Literal["voice", "text"]
Workspace = Literal["none", "code", "whiteboard"]
STATE_VERSION = 1


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", validate_assignment=False)


class CandidateInfo(_Model):
    """§34 Candidate. The first name is for speaking to them; it never reaches a model."""

    id: str
    first_name: str
    experience_years: float | None = None


class JobInfo(_Model):
    """§34 Job."""

    id: str
    title: str
    company: str


class ResumeHook(_Model):
    """§34 Resume: a verified quote from the resume that a question can start from (§36)."""

    skill: str
    field: str
    index: int
    label: str
    quote: str
    page: int | None = None
    section: str | None = None


class SkillState(_Model):
    """§34 Skills: one skill's place in the interview (§37 coverage, §39 ladder)."""

    name: str
    weight: int
    required: bool
    target: int
    """Main questions planned for it; the time controller may lower it."""
    ladder: list[str]
    """The target difficulty of each main question, from the template's mix."""
    asked: int = 0
    answered: int = 0
    rung: str | None = None
    """The difficulty of its last main question."""
    qualities: list[str] = Field(default_factory=list)
    weak_streak: int = 0
    dropped: bool = False
    """Moved on from after repeated weak answers (§38)."""

    @property
    def covered(self) -> bool:
        return self.answered > 0

    @property
    def remaining(self) -> int:
        return 0 if self.dropped else max(0, self.target - self.asked)


class PoolQuestion(_Model):
    """A question the planner may ask: the template's pinned ones, the library's, a resume one
    or a generated one, with where it came from (§36)."""

    key: str
    skill: str
    difficulty: str
    type: str
    text: str
    source: Source
    source_ref: dict[str, Any] = Field(default_factory=dict)
    topic: str | None = None
    expected_concepts: list[str] = Field(default_factory=list)
    rubric: list[dict[str, Any]] = Field(default_factory=list)
    time_limit_seconds: int | None = None
    follow_up_rules: list[dict[str, Any]] = Field(default_factory=list)
    workspace: Workspace = "none"
    languages: list[str] = Field(default_factory=list)
    used: bool = False


class AskedQuestion(_Model):
    """The question being asked now, as it was put to the candidate."""

    id: str
    position: int
    kind: QuestionKind
    stage: Stage
    text: str
    source: Source
    source_ref: dict[str, Any] = Field(default_factory=dict)
    skill: str | None = None
    topic: str | None = None
    difficulty: str | None = None
    type: str | None = None
    expected_concepts: list[str] = Field(default_factory=list)
    rubric: list[dict[str, Any]] = Field(default_factory=list)
    time_limit_seconds: int | None = None
    follow_up_rules: list[dict[str, Any]] = Field(default_factory=list)
    workspace: Workspace = "none"
    languages: list[str] = Field(default_factory=list)
    parent_id: str | None = None
    asked_at: datetime
    attempts: int = 0
    """Times it was asked again after a non-answer (a manipulation attempt, silence)."""
    follow_ups: int = 0
    """For a main question: the follow-ups asked about it."""


class AskedSummary(_Model):
    """§34 Questions Asked: one line per question."""

    id: str
    kind: QuestionKind
    skill: str | None = None
    difficulty: str | None = None
    status: str = "asked"


class QualityMark(_Model):
    """§34 Answer Quality: the live analysis's verdict per answered question."""

    question_id: str
    skill: str | None
    quality: Quality


class CodingState(_Model):
    """§34 Coding State. SP-16 adds runs and submissions; SP-09 asks the question."""

    enabled: bool = False
    status: Literal["none", "pending", "active", "done", "skipped"] = "none"
    languages: list[str] = Field(default_factory=list)
    minutes: int = 0
    question_key: str | None = None


class ProctorSummary(_Model):
    """§34 Proctor Events: counts by severity and what to remind the candidate about."""

    counts: dict[str, int] = Field(default_factory=dict)
    last_kind: str | None = None
    pending_notice: str | None = None
    """A CRITICAL event the AI should mention at the next turn ("your camera appears covered")."""


class Clock(_Model):
    started_at: datetime
    deadline_at: datetime
    paused_seconds: int = 0
    paused_since: datetime | None = None

    def remaining(self, now: datetime) -> int:
        moment = self.paused_since or now
        return max(0, int((self.deadline_at - moment).total_seconds()))

    def pause(self, now: datetime) -> None:
        if self.paused_since is None:
            self.paused_since = now

    def resume(self, now: datetime, *, extend: bool) -> int:
        """Ends a pause; with `extend` the deadline moves by its length. Returns its seconds."""
        if self.paused_since is None:
            return 0
        seconds = max(0, int((now - self.paused_since).total_seconds()))
        self.paused_since = None
        if extend:
            self.paused_seconds += seconds
            self.deadline_at += timedelta(seconds=seconds)
        return seconds

    def offset_ms(self, moment: datetime) -> int:
        """Milliseconds since the interview started: the transcript's timeline (§41)."""
        return max(0, int((moment - self.started_at).total_seconds() * 1000))


class StageMark(_Model):
    stage: Stage
    at: datetime


class InterviewState(_Model):
    version: int = STATE_VERSION
    interview_id: str
    organization_id: str
    answer_mode: AnswerMode = "voice"

    # The twelve §34 fields.
    candidate: CandidateInfo
    job: JobInfo
    resume: list[ResumeHook] = Field(default_factory=list)
    skills: list[SkillState] = Field(default_factory=list)
    questions_asked: list[AskedSummary] = Field(default_factory=list)
    topics_covered: list[str] = Field(default_factory=list)
    difficulty: str | None = None
    answer_quality: list[QualityMark] = Field(default_factory=list)
    remaining_seconds: int = 0
    current_topic: str | None = None
    coding: CodingState = Field(default_factory=CodingState)
    proctor: ProctorSummary = Field(default_factory=ProctorSummary)

    # The machine around them.
    stage: Stage = "start"
    stages: list[StageMark] = Field(default_factory=list)
    pool: list[PoolQuestion] = Field(default_factory=list)
    current: AskedQuestion | None = None
    position: int = 0
    faq_asked: int = 0
    faq: list[dict[str, str]] = Field(default_factory=list)
    """The organisation's FAQ ([{question, answer}]), the only source for final questions."""
    minutes: int = 0
    adaptive_follow_ups: bool = True
    clock: Clock
    segment_seq: int = 0
    flags: list[str] = Field(default_factory=list)
    answer_prints: list[str] = Field(default_factory=list)
    """Fingerprints of earlier answers, to flag a repeated paste."""
    ended_reason: str | None = None
    seed: int = 0

    def skill(self, name: str | None) -> SkillState | None:
        if name is None:
            return None
        folded = name.casefold()
        return next((s for s in self.skills if s.name.casefold() == folded), None)

    def enter(self, stage: Stage, now: datetime) -> bool:
        """Moves to `stage`, recording when; False if it was already there."""
        if self.stage == stage:
            return False
        self.stage = stage
        self.stages.append(StageMark(stage=stage, at=now))
        return True

    @property
    def ended(self) -> bool:
        return self.stage in ("completion", "evaluation")

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> InterviewState:
        return cls.model_validate(data)
