"""Bootstrapping identity: the first super admin, and the development seed (SP-02 spec)."""

from datetime import UTC, datetime

import pytest
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.db.session import Database
from hirevion_core.identity import PLATFORM_ORGANIZATION_ID
from hirevion_core.identity.bootstrap import (
    AccountExists,
    ProductionRefused,
    create_super_admin,
    seed_emails,
    seed_identity,
)
from hirevion_core.identity.passwords import PasswordPolicy
from hirevion_core.identity.service import AuthService, LoginOk
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.identity.tokens import lookup_token
from hirevion_core.ids import uuid7
from hirevion_core.models import Role, User, UserRole

pytestmark = pytest.mark.db

SETTINGS = IdentitySettings(web_origin="https://app.hirevion.localhost")
SEED_PASSWORD = "seed-password-for-local-dev"  # noqa: S105 (a test input)


class NoBreaches:
    async def is_breached(self, password: str) -> bool:
        return False


async def test_a_super_admin_is_invited_with_a_set_password_link(app_db: Database) -> None:
    address = f"super-{uuid7().hex[-8:]}@hirevion.example.test"
    link = await create_super_admin(app_db, email=address, name="Sam Platform", settings=SETTINGS)
    assert link.startswith("https://app.hirevion.localhost/set-password/")

    found = await lookup_token(
        app_db, link.rsplit("/", 1)[1], "set_password", now=datetime.now(UTC)
    )
    assert found is not None and found.organization_id == PLATFORM_ORGANIZATION_ID
    async with app_db.tenant(PLATFORM_ORGANIZATION_ID) as session:
        user = await session.get_one(User, found.user_id)
        keys = (
            await session.scalars(
                select(Role.key)
                .join(UserRole, UserRole.role_id == Role.id)
                .where(UserRole.user_id == user.id)
            )
        ).all()
    assert (user.status, user.password_hash, list(keys)) == ("invited", None, ["super_admin"])


async def test_an_existing_email_is_refused(app_db: Database) -> None:
    address = f"super-{uuid7().hex[-8:]}@hirevion.example.test"
    await create_super_admin(app_db, email=address, name="Sam", settings=SETTINGS)
    with pytest.raises(AccountExists):
        await create_super_admin(app_db, email=address.upper(), name="Sam", settings=SETTINGS)


async def test_seeding_is_idempotent_and_every_seeded_user_can_sign_in(
    app_db: Database, admin_engine: AsyncEngine, valkey: Redis
) -> None:
    admin = Database(admin_engine)
    first = await seed_identity(admin, app_db, password=SEED_PASSWORD, environment="development")
    again = await seed_identity(admin, app_db, password=SEED_PASSWORD, environment="development")
    assert again.organization_id == first.organization_id
    assert again.created == []

    async with admin_engine.connect() as conn:
        name = await conn.scalar(
            text("SELECT name FROM organizations WHERE id = :id"), {"id": first.organization_id}
        )
    assert name == "Acme Talent (dev)"

    auth = AuthService(app_db, valkey, policy=PasswordPolicy(NoBreaches()), settings=SETTINGS)
    for address in seed_emails():
        result = await auth.login(address, SEED_PASSWORD, ip=None, user_agent=None)
        assert isinstance(result, LoginOk), address


async def test_seeding_never_runs_in_production(
    app_db: Database, admin_engine: AsyncEngine
) -> None:
    with pytest.raises(ProductionRefused):
        await seed_identity(
            Database(admin_engine), app_db, password=SEED_PASSWORD, environment="production"
        )
