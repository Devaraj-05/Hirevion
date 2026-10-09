from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, Integer, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from hirevion_core.db.base import Base, IdMixin, TimestampMixin

DESKTOP_CHANNELS = ("stable", "beta")
DESKTOP_ARCHES = ("x64", "arm64")
RELEASE_STATUSES = ("draft", "published", "withdrawn")


class DesktopRelease(IdMixin, TimestampMixin, Base):
    """A build of the desktop app (master plan §6.18 Super Admin "Desktop releases"): platform
    data, the same for every organisation, so it has no `organization_id`."""

    __tablename__ = "desktop_releases"
    __table_args__ = (
        UniqueConstraint("channel", "arch", "version"),
        CheckConstraint("channel IN ('stable', 'beta')", name="channel"),
        CheckConstraint("arch IN ('x64', 'arm64')", name="arch"),
        CheckConstraint("status IN ('draft', 'published', 'withdrawn')", name="status"),
        CheckConstraint("rollout_percent BETWEEN 0 AND 100", name="rollout_percent"),
    )

    version: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(Text, server_default="stable")
    arch: Mapped[str] = mapped_column(Text, server_default="x64")
    notes: Mapped[str] = mapped_column(Text, server_default="")
    url: Mapped[str] = mapped_column(Text)
    signature: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    rollout_percent: Mapped[int] = mapped_column(Integer, server_default=text("100"))
    published_at: Mapped[datetime | None]
    created_by: Mapped[UUID | None]


class DesktopChannel(Base):
    """A release channel and the oldest app version it still lets sign in (PRD §28)."""

    __tablename__ = "desktop_channels"
    __table_args__ = (CheckConstraint("channel IN ('stable', 'beta')", name="channel"),)

    channel: Mapped[str] = mapped_column(Text, primary_key=True)
    minimum_version: Mapped[str] = mapped_column(Text, server_default="0.0.0")
    download_url: Mapped[str] = mapped_column(Text, server_default="")
    updated_by: Mapped[UUID | None]
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
