"""Organisations and access (SP-02b, ADR-0014): the organisation profile, departments, teams,
users and invitations, custom roles, the platform's organisations, and the resource scope.

Each operation is a plain async function over an `AsyncSession` the caller opened with
`db.tenant(...)`, taking the acting user as an `Actor`; refusals are `AccessError`s.
"""

from __future__ import annotations

from typing import Final, final
from uuid import UUID

from hirevion_core.identity import PLATFORM_ORGANIZATION_ID


@final
class Unset:
    """The type of `UNSET`: "leave this as it is", told apart from `None` ("clear it")."""

    _instance: Unset | None = None

    def __new__(cls) -> Unset:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "UNSET"


UNSET: Final = Unset()


def admin_role_key(organization_id: UUID) -> str:
    """The system role that administers an organisation: the Platform organisation's super admins,
    or everyone else's organisation admins. An organisation always keeps one active holder."""
    return "super_admin" if organization_id == PLATFORM_ORGANIZATION_ID else "org_admin"


__all__ = ["UNSET", "Unset", "admin_role_key"]
