"""The super admins' organisations (PRD §6 "Super Admin"; ADR-0014).

Each action runs in one transaction that starts in the Platform organisation's tenant (where the
caller opened it, and where an idempotency record lives), switches to the organisation it
changes, records the change in that organisation's audit chain, then switches back and records
it in the platform's chain. Every function returns with the Platform tenant current again.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.actor import Actor
from hirevion_core.access.audit import record
from hirevion_core.access.errors import Conflict, Invalid, NotFound
from hirevion_core.access.users import Invitation, create_invitation
from hirevion_core.db.search import like_escape
from hirevion_core.db.session import switch_tenant
from hirevion_core.identity import PLATFORM_ORGANIZATION_ID
from hirevion_core.identity.roles import ensure_system_roles
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.ids import uuid7
from hirevion_core.models import Organization, Role, User, WebSession

NAME_MAX = 200
REASON_MAX = 500
_SLUG = re.compile(r"[a-z0-9](?:[a-z0-9-]{1,38}[a-z0-9])")
# Words a slug can't be: they name the platform or look like its own hosts.
RESERVED_SLUGS = frozenset({"platform", "admin", "api", "app", "www"})

_LISTING = text(
    """
    SELECT id, name, slug, status, created_at, user_count FROM platform_organizations()
    WHERE (CAST(:pattern AS text) IS NULL OR name ILIKE :pattern OR slug ILIKE :pattern)
      AND (CAST(:status AS text) IS NULL OR status = :status)
      AND (CAST(:after_name AS text) IS NULL
           OR (name, id) > (CAST(:after_name AS text), CAST(:after_id AS uuid)))
    ORDER BY name, id
    LIMIT :limit
    """
)


@dataclass(frozen=True, slots=True)
class OrganizationListing:
    id: UUID
    name: str
    slug: str
    status: str
    created_at: datetime
    user_count: int


async def list_organizations(
    session: AsyncSession,
    *,
    query: str | None,
    status: str | None,
    after: tuple[str, UUID] | None,
    limit: int,
) -> list[OrganizationListing]:
    """Every organisation, the Platform one included, by name; `after` is the last row of the
    previous page."""
    pattern = None
    if query and query.strip():
        escaped = like_escape(query.strip())
        pattern = f"%{escaped}%"
    rows = await session.execute(
        _LISTING,
        {
            "pattern": pattern,
            "status": status,
            "after_name": after[0] if after else None,
            "after_id": after[1] if after else None,
            "limit": limit,
        },
    )
    return [OrganizationListing(*row) for row in rows]


def _name(value: str) -> str:
    name = value.strip()
    if not name or len(name) > NAME_MAX:
        raise Invalid("invalid-name", f"Use 1 to {NAME_MAX} characters", field="name")
    return name


def _slug(value: str) -> str:
    slug = value.strip()
    if not _SLUG.fullmatch(slug) or slug in RESERVED_SLUGS:
        raise Invalid(
            "invalid-slug",
            "Use 3 to 40 lower-case letters, digits and hyphens, not starting or ending with one",
            field="slug",
        )
    return slug


async def _actor_name(session: AsyncSession, actor: Actor) -> str:
    """Read while the Platform tenant is current: the super admin lives there."""
    return (await session.get_one(User, actor.user_id)).name


async def _listing(session: AsyncSession, organization: Organization) -> OrganizationListing:
    users = await session.scalar(select(func.count(User.id)))
    return OrganizationListing(
        organization.id,
        organization.name,
        organization.slug,
        organization.status,
        organization.created_at,
        users or 0,
    )


async def _record_both(
    session: AsyncSession,
    actor: Actor,
    action: str,
    organization_id: UUID,
    details: dict[str, object],
) -> None:
    """Records in the organisation's chain (current), then the platform's; ends there."""
    await record(
        session,
        actor,
        action,
        "organization",
        organization_id,
        organization_id=organization_id,
        details={**details, "via": "platform"},
    )
    await switch_tenant(session, PLATFORM_ORGANIZATION_ID)
    await record(session, actor, action, "organization", organization_id, details=details)


async def _invite_admin(
    session: AsyncSession,
    actor: Actor,
    organization_id: UUID,
    *,
    name: str,
    email: str,
    inviter_name: str,
    settings: IdentitySettings,
    fields: dict[str, str],
) -> None:
    # Every organisation has its system roles (`ensure_system_roles`).
    org_admin = (await session.scalars(select(Role.id).where(Role.key == "org_admin"))).one()
    try:
        await create_invitation(
            session,
            actor,
            organization_id,
            Invitation(email=email, name=name, role_ids=[org_admin]),
            inviter_name=inviter_name,
            settings=settings,
        )
    except (Conflict, Invalid) as error:
        # Point the form at its own field names (`admin_email`, not `email`).
        if error.field in fields:
            error.field = fields[error.field]
        raise


async def create_organization(
    session: AsyncSession,
    actor: Actor,
    *,
    name: str,
    slug: str,
    admin_name: str,
    admin_email: str,
    settings: IdentitySettings,
) -> OrganizationListing:
    """A new organisation with its system roles and an invited first admin."""
    organization = Organization(id=uuid7(), name=_name(name), slug=_slug(slug))
    inviter_name = await _actor_name(session, actor)
    await switch_tenant(session, organization.id)
    try:
        async with session.begin_nested():
            session.add(organization)
    except IntegrityError as error:
        if "uq_organizations_slug" in str(error.orig):
            raise Conflict(
                "slug-taken", "Another organisation uses this slug", field="slug"
            ) from error
        raise
    await ensure_system_roles(session, organization.id)
    await _invite_admin(
        session,
        actor,
        organization.id,
        name=admin_name,
        email=admin_email,
        inviter_name=inviter_name,
        settings=settings,
        fields={"email": "admin_email", "name": "admin_name"},
    )
    await session.refresh(organization)
    listing = await _listing(session, organization)
    await _record_both(
        session,
        actor,
        "platform.organization.created",
        organization.id,
        {"name": organization.name, "slug": organization.slug, "admin_email": admin_email},
    )
    return listing


async def _target(session: AsyncSession, organization_id: UUID) -> Organization:
    """Switches to `organization_id` and returns it; the Platform itself is refused."""
    if organization_id == PLATFORM_ORGANIZATION_ID:
        raise Conflict("platform-organization", "The platform organisation can't be changed here")
    await switch_tenant(session, organization_id)
    organization = await session.get(Organization, organization_id)
    if organization is None:
        await switch_tenant(session, PLATFORM_ORGANIZATION_ID)
        raise NotFound("organization-not-found", "No such organisation")
    return organization


async def set_organization_status(
    session: AsyncSession,
    actor: Actor,
    organization_id: UUID,
    *,
    suspended: bool,
    reason: str | None,
) -> OrganizationListing:
    """Suspends an organisation (its users' sessions end and nobody signs in) or reactivates it."""
    reason = (reason or "").strip() or None
    if reason is not None and len(reason) > REASON_MAX:
        raise Invalid("invalid-reason", f"Use at most {REASON_MAX} characters", field="reason")
    organization = await _target(session, organization_id)
    wanted = "suspended" if suspended else "active"
    if organization.status != wanted:
        organization.status = wanted
        if suspended:
            await session.execute(
                update(WebSession)
                .where(WebSession.revoked_at.is_(None))
                .values(revoked_at=datetime.now(UTC))
            )
        await session.flush()
        listing = await _listing(session, organization)
        action = f"platform.organization.{'suspended' if suspended else 'reactivated'}"
        details: dict[str, object] = {"reason": reason} if suspended else {}
        await _record_both(session, actor, action, organization.id, details)
        return listing
    listing = await _listing(session, organization)
    await switch_tenant(session, PLATFORM_ORGANIZATION_ID)
    return listing


async def invite_organization_admin(
    session: AsyncSession,
    actor: Actor,
    organization_id: UUID,
    *,
    name: str,
    email: str,
    settings: IdentitySettings,
) -> None:
    """Another organisation admin, for when the first invitation lapsed or its admin left."""
    inviter_name = await _actor_name(session, actor)
    await _target(session, organization_id)
    await _invite_admin(
        session,
        actor,
        organization_id,
        name=name,
        email=email,
        inviter_name=inviter_name,
        settings=settings,
        fields={},
    )
    await _record_both(
        session,
        actor,
        "platform.organization.admin_invited",
        organization_id,
        {"admin_email": email.strip().lower()},
    )
