"""Request and response bodies for the question library, templates and interview defaults."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

QuestionType = Literal[
    "technical",
    "conceptual",
    "scenario",
    "system_design",
    "coding",
    "resume_based",
    "project_based",
    "problem_solving",
]
Category = Literal["technical", "coding", "system_design", "resume_based", "custom"]
Difficulty = Literal["easy", "medium", "hard"]
QuestionStatus = Literal["draft", "approved", "archived"]
ProctoringLevel = Literal["off", "basic", "standard", "strict"]
ThirdEye = Literal["off", "optional", "required"]
CodingLanguage = Literal["python", "javascript", "typescript", "sql"]


def _python() -> list[CodingLanguage]:
    return ["python"]


class RubricCriterion(BaseModel):
    criterion: str = Field(min_length=1, max_length=200)
    weight: int = Field(ge=1, le=100)
    description: str = Field("", max_length=500)


class FollowUpRule(BaseModel):
    when: Literal["strong", "partial", "weak"]
    prompt: str = Field(min_length=1, max_length=500)


class CodingSettings(BaseModel):
    languages: list[CodingLanguage] = Field(default_factory=_python, min_length=1)
    starter_code: dict[str, str] = Field(default_factory=dict)


class QuestionBody(BaseModel):
    """A question's content (PRD §22); saving it writes a new version."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(max_length=4000)
    skill_name: str = Field(max_length=100)
    topic: str | None = Field(None, max_length=100)
    difficulty: Difficulty
    type: QuestionType
    category: Category | None = None
    expected_concepts: list[str] = Field(default_factory=list, max_length=20)
    rubric: list[RubricCriterion] = Field(default_factory=list, max_length=10)
    time_limit_seconds: int | None = Field(None, ge=30, le=3600)
    follow_up_rules: list[FollowUpRule] = Field(default_factory=list, max_length=6)
    coding: CodingSettings | None = None


class QuestionCreate(QuestionBody):
    status: Literal["draft", "approved"] = "approved"


class QuestionResponse(BaseModel):
    id: UUID
    category: Category
    status: QuestionStatus
    source: Literal["manual", "ai"]
    version: int
    text: str
    skill_name: str
    skill_id: UUID | None
    topic: str | None
    difficulty: Difficulty
    type: QuestionType
    expected_concepts: list[str]
    rubric: list[dict[str, Any]]
    time_limit_seconds: int | None
    follow_up_rules: list[dict[str, Any]]
    coding: dict[str, Any] | None
    generation: dict[str, Any] | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class QuestionVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int
    text: str
    skill_name: str
    topic: str | None
    difficulty: Difficulty
    type: QuestionType
    expected_concepts: list[str]
    rubric: list[dict[str, Any]]
    time_limit_seconds: int | None
    follow_up_rules: list[dict[str, Any]]
    coding: dict[str, Any] | None
    created_by: UUID | None
    created_at: datetime


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skills: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        min_length=1, max_length=10
    )
    count: int = Field(5, ge=1, le=10)
    experience_level: Literal["junior", "mid", "senior", "lead"] = "mid"
    job_id: UUID | None = None
    candidate_id: UUID | None = None
    template_id: UUID | None = None
    types: list[QuestionType] = Field(default_factory=list)


class GenerateResponse(BaseModel):
    drafts: list[QuestionResponse]
    skipped: int
    model: str


class SkillWeight(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    weight: int = Field(ge=1, le=100)


class RubricWeight(BaseModel):
    dimension: str
    weight: int = Field(ge=0, le=100)


class TemplateCoding(BaseModel):
    enabled: bool = False
    languages: list[CodingLanguage] = Field(default_factory=_python)
    minutes: int = Field(20, ge=5, le=90)


class Recording(BaseModel):
    screen: bool = True
    camera: bool = True
    audio: bool = True


class PinnedQuestion(BaseModel):
    question_id: UUID
    version: int = Field(ge=1)


class TemplateBody(BaseModel):
    """A template's fields (PRD §21). On an update, only the fields sent change; every update
    writes a new version and leaves the old ones as they were (PRD §80)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, max_length=200)
    description: str | None = Field(None, max_length=2000)
    duration_minutes: int | None = Field(None, ge=15, le=180)
    question_count: int | None = Field(None, ge=1, le=50)
    skills: list[SkillWeight] | None = Field(None, max_length=20)
    difficulty: dict[Difficulty, int] | None = None
    question_types: list[QuestionType] | None = None
    use_resume: bool | None = None
    use_jd: bool | None = None
    adaptive_follow_ups: bool | None = None
    coding: TemplateCoding | None = None
    proctoring_level: ProctoringLevel | None = None
    third_eye: ThirdEye | None = None
    recording: Recording | None = None
    rubric: list[RubricWeight] | None = None
    questions: list[PinnedQuestion] | None = Field(None, max_length=50)


class TemplateCreate(TemplateBody):
    name: str = Field(max_length=200)
    skills: list[SkillWeight] = Field(min_length=1, max_length=20)


class TemplateVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int
    name: str
    duration_minutes: int
    question_count: int
    skills: list[dict[str, Any]]
    difficulty: dict[str, int]
    question_types: list[str]
    use_resume: bool
    use_jd: bool
    adaptive_follow_ups: bool
    coding: dict[str, Any]
    proctoring_level: ProctoringLevel
    third_eye: ThirdEye
    recording: dict[str, bool]
    rubric: list[dict[str, Any]]
    questions: list[dict[str, Any]]
    created_by: UUID | None
    created_at: datetime


class TemplateSummary(BaseModel):
    id: UUID
    name: str
    description: str
    status: Literal["active", "archived"]
    version: int
    duration_minutes: int
    question_count: int
    proctoring_level: ProctoringLevel
    third_eye: ThirdEye
    coding: bool
    updated_at: datetime


class TemplateResponse(TemplateSummary):
    current: TemplateVersionResponse


class MatrixPreview(BaseModel):
    """Unsaved template settings, for a live skill-matrix preview."""

    model_config = ConfigDict(extra="forbid")

    question_count: int = Field(ge=1, le=50)
    skills: list[SkillWeight] = Field(min_length=1, max_length=20)
    difficulty: dict[Difficulty, int]

    @model_validator(mode="after")
    def _mix_adds_up(self) -> MatrixPreview:
        if (
            any(value < 0 for value in self.difficulty.values())
            or sum(self.difficulty.values()) != 100
        ):
            raise ValueError("the difficulty mix must be percentages that add up to 100")
        return self


class MatrixRowResponse(BaseModel):
    skill: str
    weight: int
    questions: int
    by_difficulty: dict[str, int]
    available: dict[str, int]
    gaps: dict[str, int]


class InterviewDefaults(BaseModel):
    """The organisation's defaults for new templates, and what each proctoring level means."""

    duration_minutes: int
    question_count: int
    difficulty: dict[str, int]
    question_types: list[str]
    use_resume: bool
    use_jd: bool
    adaptive_follow_ups: bool
    coding: dict[str, Any]
    proctoring_level: ProctoringLevel
    third_eye: ThirdEye
    recording: dict[str, bool]
    rubric: list[dict[str, Any]]
    proctoring_presets: dict[str, list[str]]


class InterviewDefaultsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_minutes: int | None = Field(None, ge=15, le=180)
    question_count: int | None = Field(None, ge=1, le=50)
    difficulty: dict[Difficulty, int] | None = None
    question_types: list[QuestionType] | None = None
    use_resume: bool | None = None
    use_jd: bool | None = None
    adaptive_follow_ups: bool | None = None
    coding: TemplateCoding | None = None
    proctoring_level: ProctoringLevel | None = None
    third_eye: ThirdEye | None = None
    recording: Recording | None = None
    rubric: list[RubricWeight] | None = None
