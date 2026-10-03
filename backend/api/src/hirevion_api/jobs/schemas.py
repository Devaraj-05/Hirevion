"""Request and response bodies for jobs, job descriptions and skills."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hirevion_core.jobs.jobs import JobChanges, SkillInput

JobStatus = Literal["draft", "open", "paused", "closed", "archived"]
WorkModel = Literal["onsite", "hybrid", "remote"]
EmploymentType = Literal["full_time", "part_time", "contract", "internship", "temporary"]
Importance = Literal["required", "preferred", "optional"]
DocumentStatus = Literal[
    "uploaded", "scanning", "extracting", "parsing", "parsed", "quarantined", "failed"
]

# Fields that always have a value: sending null for them is refused.
_NOT_NULL = frozenset(
    {
        "title",
        "employment_type",
        "description",
        "responsibilities",
        "qualifications",
        "domain",
        "skills",
    }
)


class SkillBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    importance: Importance = "required"
    min_years: float | None = Field(None, ge=0, le=60)


class JobFields(BaseModel):
    """The editable fields of a job; on an update, only the fields sent change."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(None, max_length=200)
    department_id: UUID | None = None
    team_id: UUID | None = None
    location: str | None = Field(None, max_length=200)
    work_model: WorkModel | None = None
    employment_type: EmploymentType | None = None
    experience_min: float | None = Field(None, ge=0, le=60)
    experience_max: float | None = Field(None, ge=0, le=60)
    description: str | None = Field(None, max_length=50_000)
    responsibilities: list[str] | None = Field(None, max_length=50)
    qualifications: list[str] | None = Field(None, max_length=50)
    domain: list[str] | None = Field(None, max_length=50)
    salary_min: float | None = Field(None, ge=0)
    salary_max: float | None = Field(None, ge=0)
    salary_currency: str | None = Field(None, min_length=3, max_length=3)
    recruiter_id: UUID | None = None
    hiring_manager_id: UUID | None = None
    skills: list[SkillBody] | None = Field(None, max_length=100)

    @model_validator(mode="after")
    def _required_values(self) -> JobFields:
        for name in _NOT_NULL & self.model_fields_set:
            if getattr(self, name) is None:
                raise ValueError(f"{name} can't be null")
        return self

    def changes(self) -> JobChanges:
        values: dict[str, Any] = {}
        for name in self.model_fields_set & set(JobChanges.__dataclass_fields__):
            value = getattr(self, name)
            if name == "skills":
                value = [
                    SkillInput(
                        skill.name,
                        skill.importance,
                        None if skill.min_years is None else Decimal(str(skill.min_years)),
                    )
                    for skill in value
                ]
            elif isinstance(value, float):
                value = Decimal(str(value))
            values[name] = value
        return JobChanges(**values)


class JobCreate(JobFields):
    title: str = Field(max_length=200)


class JobStatusChange(BaseModel):
    status: JobStatus


class JdApply(JobFields):
    """The recruiter's reviewed fields from a parsed description."""

    document_id: UUID


class SkillResponse(BaseModel):
    name: str
    skill_id: UUID | None
    importance: Importance
    min_years: float | None


class DocumentResponse(BaseModel):
    id: UUID
    status: DocumentStatus
    filename: str | None
    content_type: str | None
    size: int
    error_code: str | None
    attempts: int
    created_at: datetime
    updated_at: datetime


class JdResponse(DocumentResponse):
    """The latest description of a job: what was read from it, for review."""

    text: str | None
    flags: dict[str, Any]
    extraction: dict[str, Any] | None


class JobSummary(BaseModel):
    id: UUID
    number: int
    reference: str
    title: str
    status: JobStatus
    department_id: UUID | None
    department_name: str | None
    location: str | None
    work_model: WorkModel | None
    employment_type: EmploymentType
    recruiter_id: UUID | None
    recruiter_name: str | None
    created_at: datetime
    updated_at: datetime


class JobResponse(JobSummary):
    version: int
    team_id: UUID | None
    team_name: str | None
    experience_min: float | None
    experience_max: float | None
    description: str
    responsibilities: list[str]
    qualifications: list[str]
    domain: list[str]
    salary_min: float | None
    salary_max: float | None
    salary_currency: str | None
    hiring_manager_id: UUID | None
    hiring_manager_name: str | None
    skills: list[SkillResponse]
    jd_document_id: UUID | None
    latest_document: DocumentResponse | None


class JobVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int
    reason: str
    created_by: UUID | None
    created_at: datetime
    snapshot: dict[str, Any]


class SkillSuggestion(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    category: str
