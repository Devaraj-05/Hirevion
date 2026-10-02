"""Bootstrapping identity (SP-02 spec, "Sign-in, sessions and CSRF").

- `create_super_admin`: the first platform user, invited with a set-password link (no password
  ever goes on a command line).
- `seed_identity`: a development organisation with one real user per role, sharing the
  `HV_SEED_PASSWORD` from `.env`. It refuses to run in production.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.db.session import Database
from hirevion_core.identity import PLATFORM_ORGANIZATION_ID
from hirevion_core.identity.passwords import hash_password
from hirevion_core.identity.permissions import ORGANIZATION_ROLES
from hirevion_core.identity.roles import ensure_system_roles
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.identity.tokens import issue_token
from hirevion_core.models import Department, Organization, Role, Team, TeamMember, User, UserRole

SEED_ORGANIZATION_SLUG = "acme-dev"
SEED_ORGANIZATION_NAME = "Acme Talent (dev)"
SEED_DEPARTMENT = "Engineering"
SEED_TEAM = "Platform hiring"
SEED_SUPER_ADMIN_EMAIL = "super@hirevion.example.test"
# The same synthetic names as the web app's development sessions.
SEED_NAMES = {
    "super_admin": "Sam Platform",
    "org_admin": "Olivia Admin",
    "recruiter": "Ravi Recruiter",
    "hiring_manager": "Hema Manager",
    "interviewer": "Ishan Reviewer",
}


class AccountExists(Exception):
    """An account already uses that email address."""


class ProductionRefused(Exception):
    """Development seed data never goes into a production database."""


@dataclass(frozen=True, slots=True)
class SeedResult:
    organization_id: UUID
    created: list[str]


def seed_email(role: str) -> str:
    return f"{role.replace('_', '-')}@acme.example.test"


def seed_emails() -> list[str]:
    """Every seeded account: one per organisation role, then the platform super admin."""
    return [seed_email(role) for role in ORGANIZATION_ROLES] + [SEED_SUPER_ADMIN_EMAIL]


async def _exists(db: Database, email: str) -> bool:
    async with db.unscoped() as session:
        found = await session.execute(
            text("SELECT 1 FROM auth_user_by_email(:email)"), {"email": email}
        )
        return found.first() is not None


async def _grant(session: AsyncSession, organization_id: UUID, user_id: UUID, key: str) -> None:
    role_id = await session.scalar(
        select(Role.id).where(Role.organization_id == organization_id, Role.key == key)
    )
    if role_id is None:
        raise LookupError(f"the organisation has no {key} role")
    session.add(UserRole(organization_id=organization_id, user_id=user_id, role_id=role_id))
    await session.flush()


async def create_super_admin(
    db: Database,
    *,
    email: str,
    name: str,
    settings: IdentitySettings,
    now: datetime | None = None,
) -> str:
    """Invites a Platform super admin and returns their set-password link."""
    email = email.strip()
    if await _exists(db, email):
        raise AccountExists(email)
    async with db.tenant(PLATFORM_ORGANIZATION_ID) as session:
        user = User(
            organization_id=PLATFORM_ORGANIZATION_ID, email=email, name=name, status="invited"
        )
        session.add(user)
        await session.flush()
        await _grant(session, PLATFORM_ORGANIZATION_ID, user.id, "super_admin")
        token = await issue_token(
            session,
            organization_id=PLATFORM_ORGANIZATION_ID,
            user_id=user.id,
            purpose="set_password",
            ttl=timedelta(hours=settings.set_password_token_hours),
            now=now or datetime.now(UTC),
        )
    return f"{settings.web_origin.rstrip('/')}/set-password/{token}"


async def seed_identity(
    admin: Database, db: Database, *, password: str, environment: str
) -> SeedResult:
    """Creates what's missing of the development organisation and its users. `admin` (the
    migration role) creates the organisation, which the application role can't."""
    if environment == "production":
        raise ProductionRefused
    async with admin.unscoped() as session:
        organization_id = await session.scalar(
            select(Organization.id).where(Organization.slug == SEED_ORGANIZATION_SLUG)
        )
        if organization_id is None:
            organization = Organization(name=SEED_ORGANIZATION_NAME, slug=SEED_ORGANIZATION_SLUG)
            session.add(organization)
            await session.flush()
            organization_id = organization.id
        await ensure_system_roles(session, organization_id)

    accounts = [(organization_id, role, seed_email(role)) for role in ORGANIZATION_ROLES]
    accounts.append((PLATFORM_ORGANIZATION_ID, "super_admin", SEED_SUPER_ADMIN_EMAIL))
    password_hash = hash_password(password)
    now = datetime.now(UTC)
    created: list[str] = []
    for owner, role, email in accounts:
        if await _exists(db, email):
            continue
        async with db.tenant(owner) as session:
            user = User(
                organization_id=owner,
                email=email,
                name=SEED_NAMES[role],
                status="active",
                password_hash=password_hash,
                email_verified_at=now,
                password_changed_at=now,
            )
            session.add(user)
            await session.flush()
            await _grant(session, owner, user.id, role)
        created.append(email)
    async with db.tenant(organization_id) as session:
        await _seed_structure(session, organization_id)
    return SeedResult(organization_id=organization_id, created=created)


async def _seed_structure(session: AsyncSession, organization_id: UUID) -> None:
    """A department and a team holding the seeded recruiter, so the admin pages and the team
    limit have something to show (ADR-0014)."""
    department = await session.scalar(
        select(Department).where(Department.name == SEED_DEPARTMENT)
    ) or Department(organization_id=organization_id, name=SEED_DEPARTMENT)
    session.add(department)
    await session.flush()
    team = await session.scalar(select(Team).where(Team.name == SEED_TEAM)) or Team(
        organization_id=organization_id, name=SEED_TEAM, department_id=department.id
    )
    session.add(team)
    await session.flush()
    recruiter = await session.scalar(select(User.id).where(User.email == seed_email("recruiter")))
    if recruiter is not None and await session.get(TeamMember, (team.id, recruiter)) is None:
        session.add(TeamMember(organization_id=organization_id, team_id=team.id, user_id=recruiter))
