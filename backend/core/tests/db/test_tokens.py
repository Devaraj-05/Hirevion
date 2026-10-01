"""Single-use emailed tokens (password reset, email verification, first password)."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from hirevion_core.db.session import Database
from hirevion_core.identity.tokens import claim_token, issue_token, lookup_token

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]
NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


async def issue(db: Database, organization_id: UUID, user_id: UUID, **extra) -> str:
    async with db.tenant(organization_id) as session:
        return await issue_token(
            session,
            organization_id=organization_id,
            user_id=user_id,
            purpose=extra.pop("purpose", "reset_password"),
            ttl=extra.pop("ttl", timedelta(minutes=30)),
            now=NOW,
            **extra,
        )


async def use(db: Database, token: str, purpose: str, at: datetime = NOW):
    found = await lookup_token(db, token, purpose, now=at)
    if found is None:
        return None
    async with db.tenant(found.organization_id) as session:
        return await claim_token(session, found, now=at)


async def test_a_token_works_once_and_needs_no_tenant_to_find(
    app_db: Database, make_organization: MakeOrganization, make_user
) -> None:
    acme = await make_organization("Acme")
    ravi = await make_user(acme)
    token = await issue(app_db, acme, ravi)

    found = await lookup_token(app_db, token, "reset_password", now=NOW)
    assert found is not None
    assert (found.organization_id, found.user_id) == (acme, ravi)

    claimed = await use(app_db, token, "reset_password")
    assert claimed is not None and claimed.used_at == NOW
    assert await use(app_db, token, "reset_password") is None


async def test_a_found_token_can_be_claimed_only_once(
    app_db: Database, make_organization: MakeOrganization, make_user
) -> None:
    acme = await make_organization("Acme")
    token = await issue(app_db, acme, await make_user(acme))
    found = await lookup_token(app_db, token, "reset_password", now=NOW)
    assert found is not None
    async with app_db.tenant(acme) as session:
        assert await claim_token(session, found, now=NOW) is not None
    async with app_db.tenant(acme) as session:
        assert await claim_token(session, found, now=NOW) is None


async def test_expired_or_misused_tokens_fail(
    app_db: Database, make_organization: MakeOrganization, make_user
) -> None:
    acme = await make_organization("Acme")
    ravi = await make_user(acme)
    token = await issue(app_db, acme, ravi)
    assert await use(app_db, token, "reset_password", at=NOW + timedelta(minutes=31)) is None
    assert await use(app_db, token, "verify_email") is None
    assert await use(app_db, "made-up", "reset_password") is None


async def test_an_email_change_token_carries_the_new_address(
    app_db: Database, make_organization: MakeOrganization, make_user
) -> None:
    acme = await make_organization("Acme")
    ravi = await make_user(acme)
    token = await issue(
        app_db, acme, ravi, purpose="verify_email", ttl=timedelta(hours=24), new_email="n@x.test"
    )
    claimed = await use(app_db, token, "verify_email")
    assert claimed is not None and claimed.new_email == "n@x.test"
