from __future__ import annotations

from datetime import datetime

from sqlalchemy import Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from hirevion_core.db.base import Base, IdMixin, TenantMixin, TimestampMixin


class Department(IdMixin, TenantMixin, TimestampMixin, Base):
    """A part of an organisation (PRD §9). Archived rather than deleted, so jobs (SP-04) can
    keep pointing at one. Names are unique per organisation, ignoring case."""

    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("organization_id", "name"),
        UniqueConstraint("organization_id", "id"),
    )

    name: Mapped[str] = mapped_column(CITEXT)
    description: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None]
