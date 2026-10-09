"""The desktop release registry (PRD §26, §28; master plan §6.18; ADR-0021).

Each channel (`stable`, `beta`) has a minimum version: an older app can't sign in (`426`).
Releases are per channel and architecture, with a rollout percentage: a device is inside a
partial rollout when `sha256("{jkt}:{version}")` falls in the first `rollout_percent` of 100
buckets, so the same device always gets the same answer and widening a rollout only adds
devices. Without a device key, only full rollouts count. The Tauri updater never gets an older
version than it runs (no downgrades).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.actor import Actor
from hirevion_core.access.audit import record
from hirevion_core.access.errors import Conflict, Invalid, NotFound
from hirevion_core.models import DesktopChannel, DesktopRelease
from hirevion_core.models.desktop_release import DESKTOP_ARCHES, DESKTOP_CHANNELS

_VERSION = re.compile(r"(\d{1,6})\.(\d{1,6})\.(\d{1,6})(?:-([0-9A-Za-z.-]{1,40}))?")
# Tauri's architecture names for ours.
TAURI_ARCHES = {"x86_64": "x64", "aarch64": "arm64"}
CheckStatus = Literal["ok", "update-available", "update-required"]


@dataclass(frozen=True, order=True, slots=True)
class Version:
    """A semantic version; a pre-release sorts before its release."""

    major: int
    minor: int
    patch: int
    release: int
    """1 for a release, 0 for a pre-release (so 1.5.0-beta.1 < 1.5.0)."""
    pre: tuple[tuple[int, int | str], ...]

    @classmethod
    def parse(cls, text: str) -> Version:
        match = _VERSION.fullmatch(text.strip())
        if match is None:
            raise ValueError(f"not a version: {text!r}")
        major, minor, patch, pre = match.groups()
        parts: tuple[tuple[int, int | str], ...] = ()
        if pre:
            parts = tuple((0, int(p)) if p.isdigit() else (1, p) for p in pre.split("."))
        return cls(int(major), int(minor), int(patch), 0 if pre else 1, parts)


def parse_version(text: str) -> Version:
    try:
        return Version.parse(text)
    except ValueError as error:
        raise Invalid("invalid-version", "Use a version like 1.4.0", field="version") from error


def in_rollout(jkt: str | None, version: str, percent: int) -> bool:
    if percent >= 100:
        return True
    if jkt is None or percent <= 0:
        return False
    bucket = int(hashlib.sha256(f"{jkt}:{version}".encode()).hexdigest()[:8], 16) % 100
    return bucket < percent


@dataclass(frozen=True, slots=True)
class ReleaseCheck:
    status: CheckStatus
    latest: DesktopRelease | None
    minimum_version: str
    download_url: str


def _channel_name(channel: str) -> str:
    if channel not in DESKTOP_CHANNELS:
        raise Invalid("invalid-channel", "Use the stable or beta channel", field="channel")
    return channel


def _arch_name(arch: str) -> str:
    arch = TAURI_ARCHES.get(arch, arch)
    if arch not in DESKTOP_ARCHES:
        raise Invalid("invalid-arch", "Use x64 or arm64", field="arch")
    return arch


async def get_channel(session: AsyncSession, channel: str) -> DesktopChannel:
    row = await session.get(DesktopChannel, _channel_name(channel))
    if row is None:
        raise NotFound("channel-not-found", "No such channel")
    return row


async def latest_release(
    session: AsyncSession, channel: str, arch: str, jkt: str | None
) -> DesktopRelease | None:
    """The newest published release this device may have."""
    rows = (
        await session.scalars(
            select(DesktopRelease).where(
                DesktopRelease.channel == _channel_name(channel),
                DesktopRelease.arch == _arch_name(arch),
                DesktopRelease.status == "published",
            )
        )
    ).all()
    eligible = [row for row in rows if in_rollout(jkt, row.version, row.rollout_percent)]
    return max(eligible, key=lambda row: Version.parse(row.version), default=None)


async def is_outdated(session: AsyncSession, version: str, channel: str) -> DesktopChannel | None:
    """The channel when `version` is below its minimum (the app must update); else None."""
    row = await get_channel(session, channel)
    if parse_version(version) < Version.parse(row.minimum_version):
        return row
    return None


async def check(
    session: AsyncSession, version: str, channel: str, arch: str, jkt: str | None
) -> ReleaseCheck:
    current = parse_version(version)
    row = await get_channel(session, channel)
    latest = await latest_release(session, channel, arch, jkt)
    if current < Version.parse(row.minimum_version):
        status: CheckStatus = "update-required"
    elif latest is not None and Version.parse(latest.version) > current:
        status = "update-available"
    else:
        status = "ok"
    # The channel's download page, never a release's updater bundle (the app installs that).
    return ReleaseCheck(status, latest, row.minimum_version, row.download_url)


async def update_manifest(
    session: AsyncSession,
    target: str,
    arch: str,
    current_version: str,
    *,
    channel: str = "stable",
    jkt: str | None = None,
) -> dict[str, object] | None:
    """The Tauri v2 updater's answer, or None (204) when nothing newer applies."""
    if target != "windows":
        return None
    our_arch = _arch_name(arch)
    current = parse_version(current_version)
    latest = await latest_release(session, channel, our_arch, jkt)
    if latest is None or Version.parse(latest.version) <= current:
        return None
    tauri_arch = next(name for name, ours in TAURI_ARCHES.items() if ours == our_arch)
    published = latest.published_at or latest.created_at
    return {
        "version": latest.version,
        "notes": latest.notes,
        "pub_date": published.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platforms": {
            f"windows-{tauri_arch}": {"signature": latest.signature, "url": latest.url},
        },
    }


# Platform administration (super admins; audited in the platform's chain)


@dataclass(frozen=True, slots=True)
class NewRelease:
    version: str
    channel: str
    arch: str
    url: str
    signature: str
    notes: str = ""
    rollout_percent: int = 100


def _url(value: str) -> str:
    parts = urlsplit(value.strip())
    if parts.scheme != "https" or not parts.netloc:
        raise Invalid("invalid-url", "Use an https:// download address", field="url")
    return value.strip()


def _percent(value: int) -> int:
    if not 0 <= value <= 100:
        raise Invalid("invalid-rollout", "Use 0 to 100 percent", field="rollout_percent")
    return value


async def list_releases(session: AsyncSession) -> Sequence[DesktopRelease]:
    rows = (await session.scalars(select(DesktopRelease))).all()
    return sorted(
        rows, key=lambda row: (row.channel, row.arch, Version.parse(row.version)), reverse=True
    )


async def create_release(session: AsyncSession, actor: Actor, new: NewRelease) -> DesktopRelease:
    parse_version(new.version)
    if not new.signature.strip():
        raise Invalid(
            "signature-required", "Paste the update's minisign signature", field="signature"
        )
    release = DesktopRelease(
        version=new.version.strip(),
        channel=_channel_name(new.channel),
        arch=_arch_name(new.arch),
        url=_url(new.url),
        signature=new.signature.strip(),
        notes=new.notes.strip()[:5000],
        status="draft",
        rollout_percent=_percent(new.rollout_percent),
        created_by=actor.user_id,
    )
    try:
        async with session.begin_nested():
            session.add(release)
            await session.flush()
    except IntegrityError as error:
        raise Conflict(
            "release-exists", "That version is already registered for this channel and architecture"
        ) from error
    await record(
        session,
        actor,
        "desktop_release.created",
        "desktop_release",
        release.id,
        details={"version": release.version, "channel": release.channel, "arch": release.arch},
    )
    return release


async def update_release(
    session: AsyncSession,
    actor: Actor,
    release_id: UUID,
    *,
    status: str | None = None,
    rollout_percent: int | None = None,
    notes: str | None = None,
) -> DesktopRelease:
    release = await session.get(DesktopRelease, release_id)
    if release is None:
        raise NotFound("release-not-found", "No such release")
    changed: dict[str, object] = {}
    if status is not None and status != release.status:
        if status not in ("draft", "published", "withdrawn"):
            raise Invalid("invalid-status", "Unknown release status", field="status")
        release.status = status
        if status == "published" and release.published_at is None:
            release.published_at = datetime.now(UTC)
        changed["status"] = status
    if rollout_percent is not None and rollout_percent != release.rollout_percent:
        release.rollout_percent = _percent(rollout_percent)
        changed["rollout_percent"] = rollout_percent
    if notes is not None and notes.strip() != release.notes:
        release.notes = notes.strip()[:5000]
        changed["notes"] = True
    if changed:
        await session.flush()
        await record(
            session,
            actor,
            "desktop_release.updated",
            "desktop_release",
            release.id,
            details={"version": release.version, **changed},
        )
    return release


async def set_channel(
    session: AsyncSession,
    actor: Actor,
    channel: str,
    *,
    minimum_version: str | None = None,
    download_url: str | None = None,
) -> DesktopChannel:
    row = await get_channel(session, channel)
    changed: dict[str, object] = {}
    if minimum_version is not None and minimum_version != row.minimum_version:
        parse_version(minimum_version)
        row.minimum_version = minimum_version.strip()
        changed["minimum_version"] = row.minimum_version
    if download_url is not None and download_url != row.download_url:
        row.download_url = _url(download_url) if download_url.strip() else ""
        changed["download_url"] = row.download_url
    if changed:
        row.updated_by = actor.user_id
        row.updated_at = datetime.now(UTC)
        await session.flush()
        await record(
            session,
            actor,
            "desktop_channel.updated",
            "desktop_channel",
            None,
            details={"channel": row.channel, **changed},
        )
    return row
