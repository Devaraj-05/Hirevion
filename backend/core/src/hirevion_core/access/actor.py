from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Actor:
    """The signed-in user making a change: who they are, where, and what they may grant."""

    user_id: UUID
    organization_id: UUID
    permissions: frozenset[str]
    ip: str | None = None
    user_agent: str | None = None
