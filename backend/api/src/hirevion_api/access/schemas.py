"""Request and response bodies of the organisation, structure, user, role and platform routes.

PATCH bodies tell "leave it" (field absent) apart from "clear it" (`null`): `patched()` keeps
only the fields the client sent, and the domain treats the rest as `UNSET`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

Name = Annotated[str, Field(min_length=1, max_length=200)]
Description = Annotated[str, Field(max_length=500)]


class Patch(BaseModel):
    model_config = ConfigDict(extra="forbid")


def not_null(value: object) -> object:
    """For PATCH fields that can be left out but not cleared."""
    if value is None:
        raise ValueError("can't be null; leave it out to keep the current value")
    return value


def patched(body: Patch) -> dict[str, Any]:
    """The fields the client sent, as keyword arguments for an update."""
    return {name: getattr(body, name) for name in body.model_fields_set}


# The organisation profile


class OrganizationProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    status: Literal["active", "suspended"]
    website: str | None
    country: str = Field(description="ISO 3166-1 alpha-2 code.")
    timezone: str = Field(description="IANA time zone, e.g. Asia/Kolkata.")
    default_locale: Literal["en-IN", "en-US"]


class OrganizationProfileUpdate(Patch):
    name: Name | None = None
    website: Annotated[str, Field(max_length=300)] | None = None
    country: Annotated[str, Field(pattern=r"^[A-Z]{2}$")] | None = None
    timezone: Annotated[str, Field(max_length=64)] | None = None
    default_locale: Literal["en-IN", "en-US"] | None = None

    @field_validator("name", "country", "timezone", "default_locale")
    @classmethod
    def _present(cls, value: object) -> object:
        return not_null(value)


# Departments and teams


class DepartmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    archived_at: datetime | None
    created_at: datetime


class DepartmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=100)]
    description: Description | None = None


class DepartmentUpdate(Patch):
    name: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    description: Description | None = None
    archived: bool | None = None

    @field_validator("name", "archived")
    @classmethod
    def _present(cls, value: object) -> object:
        return not_null(value)


class TeamResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    department_id: UUID | None
    department_name: str | None
    member_count: int
    archived_at: datetime | None
    created_at: datetime


class TeamCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=100)]
    description: Description | None = None
    department_id: UUID | None = None


class TeamUpdate(Patch):
    name: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    description: Description | None = None
    department_id: UUID | None = None
    archived: bool | None = None

    @field_validator("name", "archived")
    @classmethod
    def _present(cls, value: object) -> object:
        return not_null(value)


class MemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: str
    status: Literal["invited", "active", "disabled"]
