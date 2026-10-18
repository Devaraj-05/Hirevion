"""Shared pieces of the administration routes."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_api.authz import Principal
from hirevion_api.deps import get_db
from hirevion_core.access.scope import resource_scope
from hirevion_core.interviews import assignment
from hirevion_core.models import Interview


def own_tenant(request: Request, principal: Principal) -> AbstractAsyncContextManager[AsyncSession]:
    """A transaction in the principal's own organisation."""
    return get_db(request).tenant(principal.organization_id)


async def scoped_interview(
    session: AsyncSession, principal: Principal, interview_id: UUID
) -> Interview:
    """The interview, if the caller's resource scope reaches it (a reviewer sees only the ones
    assigned to them); `interview-not-found` otherwise."""
    scope = await resource_scope(session, principal.user_id)
    return await assignment.get_interview(
        session, interview_id, scope, reviewer_only=principal.reviewer_only
    )


def idempotency_scope(principal: Principal) -> str:
    """Whose retries an `Idempotency-Key` is matched against."""
    return f"user:{principal.user_id}"
