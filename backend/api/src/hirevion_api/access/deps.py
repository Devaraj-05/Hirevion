"""Shared pieces of the administration routes."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_api.authz import Principal
from hirevion_api.deps import get_db


def own_tenant(request: Request, principal: Principal) -> AbstractAsyncContextManager[AsyncSession]:
    """A transaction in the principal's own organisation."""
    return get_db(request).tenant(principal.organization_id)


def idempotency_scope(principal: Principal) -> str:
    """Whose retries an `Idempotency-Key` is matched against."""
    return f"user:{principal.user_id}"
