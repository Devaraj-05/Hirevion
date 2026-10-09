"""Request and response bodies of the organisation, structure, user, role and platform routes.

PATCH bodies tell "leave it" (field absent) apart from "clear it" (`null`): `patched()` keeps
only the fields the client sent, and the domain treats the rest as `UNSET`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from hirevion_api.auth.schemas import Email, Permission

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
    support_email: str | None = Field(
        None, description="Where candidates write for help (invitations, the portal)."
    )


class OrganizationProfileUpdate(Patch):
    name: Name | None = None
    website: Annotated[str, Field(max_length=300)] | None = None
    support_email: Annotated[str, Field(max_length=254)] | None = None
    country: Annotated[str, Field(pattern=r"^[A-Z]{2}$")] | None = None
    timezone: Annotated[str, Field(max_length=64)] | None = None
    default_locale: Literal["en-IN", "en-US"] | None = None

    @field_validator("name", "country", "timezone", "default_locale")
    @classmethod
    def _present(cls, value: object) -> object:
        return not_null(value)


class CandidateAccessSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_device_otp: bool = Field(
        True, description="Email candidates a one-time code when they sign in on a new device."
    )


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


# Users


class RoleRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key: str | None = Field(description="The system role's key; null for a custom role.")
    name: str


class TeamRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str


class UserResponse(BaseModel):
    id: UUID
    name: str
    email: str
    status: Literal["invited", "active", "disabled"]
    access_scope: Literal["organization", "teams"] = Field(
        description="`teams`: only their teams' work, and their own."
    )
    locale: Literal["en-IN", "en-US"]
    roles: list[RoleRef]
    teams: list[TeamRef]
    created_at: datetime


class UserInvite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Email
    name: Name
    role_ids: list[UUID] = Field(description="At least one.")
    team_ids: list[UUID] = Field(default_factory=list)
    access_scope: Literal["organization", "teams"] = "organization"
    locale: Literal["en-IN", "en-US"] = "en-IN"


class UserUpdate(Patch):
    name: Name | None = None
    access_scope: Literal["organization", "teams"] | None = None
    team_ids: list[UUID] | None = Field(default=None, description="Replaces their teams.")

    @field_validator("name", "access_scope", "team_ids")
    @classmethod
    def _present(cls, value: object) -> object:
        return not_null(value)


class UserRolesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_ids: list[UUID] = Field(description="Replaces their roles; at least one.")


# Roles


class RoleResponse(BaseModel):
    id: UUID
    key: str | None = Field(description="The system role's key; null for a custom role.")
    name: str
    description: str | None
    system: bool = Field(description="Built in: can't be changed or deleted.")
    permissions: list[Permission] = Field(description="What it grants, in catalogue order.")
    member_count: int


class RoleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=60)]
    description: Description | None = None
    permissions: list[Permission]


class RoleUpdate(Patch):
    name: Annotated[str, Field(min_length=1, max_length=60)] | None = None
    description: Description | None = None
    permissions: list[Permission] | None = None

    @field_validator("name", "permissions")
    @classmethod
    def _present(cls, value: object) -> object:
        return not_null(value)


class PermissionResponse(BaseModel):
    name: Permission
    area: str = Field(description="The part before the first dot, for grouping.")


# The platform's organisations


class OrganizationListingResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    status: Literal["active", "suspended"]
    created_at: datetime
    user_count: int


class OrganizationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    slug: Annotated[str, Field(min_length=3, max_length=40)]
    admin_name: Name
    admin_email: Email


class OrganizationSuspend(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, Field(max_length=500)] | None = None


class OrganizationAdminInvite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    email: Email
