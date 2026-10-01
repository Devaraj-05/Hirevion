from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from hirevion_core.db.base import Base, IdMixin, TenantMixin, TimestampMixin

USER_STATUSES = ("invited", "active", "disabled")


class User(IdMixin, TenantMixin, TimestampMixin, Base):
    """A recruiter-side account. It belongs to one organisation; its email is unique across the
    platform (case-insensitive). `invited` users have no password yet."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("status IN ('invited', 'active', 'disabled')", name="status"),
        # The target of the composite (organization_id, user_id) foreign keys.
        UniqueConstraint("organization_id", "id"),
    )

    email: Mapped[str] = mapped_column(CITEXT, unique=True)
    name: Mapped[str] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(Text, server_default="en-IN")
    status: Mapped[str] = mapped_column(Text, server_default="invited")
    password_hash: Mapped[str | None] = mapped_column(Text)
    email_verified_at: Mapped[datetime | None]
    password_changed_at: Mapped[datetime | None]
