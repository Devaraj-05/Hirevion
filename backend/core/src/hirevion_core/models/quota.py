from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from hirevion_core.db.base import Base


class Quota(Base):
    """A per-organisation limit on a meter per period, e.g. `ai.cost.usd` per month.

    Tenants can read their quotas; platform administration (SP-22) sets them.
    """

    __tablename__ = "quotas"
    __table_args__ = (CheckConstraint("period IN ('month')", name="period"),)

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    meter: Mapped[str] = mapped_column(Text, primary_key=True)
    period: Mapped[str] = mapped_column(Text, primary_key=True)
    limit_value: Mapped[Decimal] = mapped_column(Numeric)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
