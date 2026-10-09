"""The organisation profile (PRD §9 "Organization profile")."""

from __future__ import annotations

import re
import zoneinfo
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access import UNSET, Unset
from hirevion_core.access.actor import Actor
from hirevion_core.access.audit import record
from hirevion_core.access.errors import Invalid, Refused
from hirevion_core.identity import PLATFORM_ORGANIZATION_ID
from hirevion_core.models import Organization, OrganizationSettings
from hirevion_core.models.organization import ORGANIZATION_LOCALES

NAME_MAX = 200
WEBSITE_MAX = 300
_COUNTRY = re.compile(r"[A-Z]{2}")
_EMAIL = re.compile(r"[^@\s]{1,64}@[^@\s]+\.[^@\s]+")


@dataclass(frozen=True, slots=True)
class ProfileChanges:
    """The fields to change; `UNSET` leaves one as it is, and `website=None` clears it."""

    name: str | Unset = UNSET
    website: str | Unset | None = UNSET
    country: str | Unset = UNSET
    timezone: str | Unset = UNSET
    default_locale: str | Unset = UNSET
    support_email: str | Unset | None = UNSET


def _refuse_platform(actor: Actor) -> None:
    if actor.organization_id == PLATFORM_ORGANIZATION_ID:
        raise Refused(
            "platform-organization",
            "The platform has no organisation profile",
            detail="Manage organisations under Platform → Organisations.",
        )


async def get_profile(session: AsyncSession, actor: Actor) -> Organization:
    _refuse_platform(actor)
    return await session.get_one(Organization, actor.organization_id)


def _checked(changes: ProfileChanges) -> dict[str, str | None]:
    values: dict[str, str | None] = {}
    if not isinstance(changes.name, Unset):
        name = changes.name.strip()
        if not name or len(name) > NAME_MAX:
            raise Invalid("invalid-name", f"Use 1 to {NAME_MAX} characters", field="name")
        values["name"] = name
    if not isinstance(changes.website, Unset):
        website = (changes.website or "").strip() or None
        if website is not None:
            parts = urlsplit(website)
            if parts.scheme not in ("http", "https") or not parts.netloc:
                raise Invalid(
                    "invalid-website", "Use a web address starting https://", field="website"
                )
            if len(website) > WEBSITE_MAX:
                raise Invalid(
                    "invalid-website", f"Use at most {WEBSITE_MAX} characters", field="website"
                )
        values["website"] = website
    if not isinstance(changes.country, Unset):
        if not _COUNTRY.fullmatch(changes.country):
            raise Invalid("invalid-country", "Use a two-letter country code", field="country")
        values["country"] = changes.country
    if not isinstance(changes.timezone, Unset):
        if changes.timezone not in zoneinfo.available_timezones():
            raise Invalid("invalid-timezone", "Unknown time zone", field="timezone")
        values["timezone"] = changes.timezone
    if not isinstance(changes.support_email, Unset):
        email = (changes.support_email or "").strip() or None
        if email is not None and not _EMAIL.fullmatch(email):
            raise Invalid(
                "invalid-email", "Use an email address like help@example.com", field="support_email"
            )
        values["support_email"] = email
    if not isinstance(changes.default_locale, Unset):
        if changes.default_locale not in ORGANIZATION_LOCALES:
            raise Invalid("invalid-locale", "Unsupported language", field="default_locale")
        values["default_locale"] = changes.default_locale
    return values


async def update_profile(
    session: AsyncSession, actor: Actor, changes: ProfileChanges
) -> Organization:
    _refuse_platform(actor)
    values = _checked(changes)
    organization = await session.get_one(Organization, actor.organization_id)
    changed = sorted(name for name, value in values.items() if getattr(organization, name) != value)
    for name in changed:
        setattr(organization, name, values[name])
    if changed:
        await session.flush()
        await record(
            session,
            actor,
            "organization.profile.updated",
            "organization",
            organization.id,
            details={"fields": changed},
        )
    return organization


CANDIDATE_ACCESS_DEFAULTS: dict[str, bool] = {"new_device_otp": True}


async def candidate_access(session: AsyncSession, actor: Actor) -> dict[str, bool]:
    """How the organisation's candidates sign in (SP-07c)."""
    _refuse_platform(actor)
    row = await session.scalar(select(OrganizationSettings))
    saved = row.candidate_access if row else {}
    return {
        key: bool(saved.get(key, default)) for key, default in CANDIDATE_ACCESS_DEFAULTS.items()
    }


async def save_candidate_access(
    session: AsyncSession, actor: Actor, values: dict[str, bool]
) -> dict[str, bool]:
    _refuse_platform(actor)
    merged = {**(await candidate_access(session, actor)), **values}
    row = await session.scalar(select(OrganizationSettings))
    if row is None:
        row = OrganizationSettings(organization_id=actor.organization_id)
        session.add(row)
    row.candidate_access = merged
    row.updated_by = actor.user_id
    await session.flush()
    await record(
        session,
        actor,
        "organization.candidate_access.changed",
        "organization",
        actor.organization_id,
        details=dict(merged),
    )
    return merged
