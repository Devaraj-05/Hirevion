from __future__ import annotations

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, SmallInteger, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from hirevion_core.db.base import Base, IdMixin, TimestampMixin


class FeatureFlag(IdMixin, TimestampMixin, Base):
    """A flag that is global (`organization_id` NULL) or overrides it for one organisation.

    The application role can only read flags; they are changed by platform administration.
    """

    __tablename__ = "feature_flags"
    __table_args__ = (
        UniqueConstraint("key", "organization_id", postgresql_nulls_not_distinct=True),
        CheckConstraint("rollout_percent BETWEEN 0 AND 100", name="rollout_percent"),
    )

    key: Mapped[str] = mapped_column(Text)
    organization_id: Mapped[UUID | None] = mapped_column(ForeignKey("organizations.id"), index=True)
    enabled: Mapped[bool] = mapped_column(server_default=text("false"))
    rollout_percent: Mapped[int] = mapped_column(SmallInteger, server_default=text("100"))
    description: Mapped[str] = mapped_column(Text, server_default="")
