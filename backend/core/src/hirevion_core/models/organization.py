from __future__ import annotations

from sqlalchemy import CheckConstraint, Text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from hirevion_core.db.base import Base, IdMixin, TimestampMixin

ORGANIZATION_STATUSES = ("active", "suspended")


class Organization(IdMixin, TimestampMixin, Base):
    """A tenant. Its row-level security policy compares `id` with the current organisation."""

    __tablename__ = "organizations"
    __table_args__ = (CheckConstraint("status IN ('active', 'suspended')", name="status"),)

    name: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(CITEXT, unique=True)
    status: Mapped[str] = mapped_column(Text, server_default="active")
