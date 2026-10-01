"""Request and response bodies of `/api/v1/auth/*`."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, WithJsonSchema

from hirevion_core.identity.permissions import PERMISSIONS

# A permission name; the OpenAPI document lists them all, so the generated client types the
# catalogue and the web app's own list is checked against it at compile time.
Permission = Annotated[str, WithJsonSchema({"type": "string", "enum": list(PERMISSIONS)})]

Email = Annotated[str, Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")]
# Long enough for any acceptable password; the policy does the real checking.
Password = Annotated[str, Field(min_length=1, max_length=1024)]
Token = Annotated[str, Field(min_length=1, max_length=256)]


class LoginRequest(BaseModel):
    email: Email
    password: Password


class SessionUser(BaseModel):
    id: UUID
    name: str
    email: str


class SessionOrganization(BaseModel):
    id: UUID
    name: str


class SessionResponse(BaseModel):
    """The signed-in session (ADR-0012). `organization` is null for platform super admins."""

    user: SessionUser
    organization: SessionOrganization | None
    roles: list[str] = Field(description="The user's system roles, by key.")
    custom_roles: list[str] = Field(
        default_factory=list, description="The user's custom roles, by name."
    )
    permissions: list[Permission]


class SessionItem(BaseModel):
    id: UUID
    created_at: datetime
    last_seen_at: datetime
    ip: str | None
    user_agent: str | None
    current: bool = Field(description="This browser's own session.")


class PasswordChangeRequest(BaseModel):
    current_password: Password
    new_password: Password


class StepUpRequest(BaseModel):
    password: Password


class ForgotPasswordRequest(BaseModel):
    email: Email


class TokenPasswordRequest(BaseModel):
    token: Token
    password: Password


class EmailChangeRequest(BaseModel):
    new_email: Email
    password: Password


class EmailVerifyRequest(BaseModel):
    token: Token
