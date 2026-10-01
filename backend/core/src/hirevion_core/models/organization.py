from __future__ import annotations

from sqlalchemy import CheckConstraint, Text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from hirevion_core.db.base import Base, IdMixin, TimestampMixin

ORGANIZATION_STATUSES = ("active", "suspended")
ORGANIZATION_LOCALES = ("en-IN", "en-US")


class Organization(IdMixin, TimestampMixin, Base):
    """A tenant. Its row-level security policy compares `id` with the current organisation.
    The profile columns (website, country, time zone, default language) are PRD §9's
    "Organization profile"."""

    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'suspended')", name="status"),
        CheckConstraint("country ~ '^[A-Z]{2}$'", name="country"),
        CheckConstraint("default_locale IN ('en-IN', 'en-US')", name="default_locale"),
    )

    name: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(CITEXT, unique=True)
    status: Mapped[str] = mapped_column(Text, server_default="active")
    website: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str] = mapped_column(Text, server_default="IN")
    timezone: Mapped[str] = mapped_column(Text, server_default="Asia/Kolkata")
    default_locale: Mapped[str] = mapped_column(Text, server_default="en-IN")
