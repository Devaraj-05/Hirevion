from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hirevion_core.db.base import Base
from hirevion_core.ids import uuid7


def _utc_now() -> datetime:
    return datetime.now(UTC)


class UsageEvent(Base):
    """One measured use of a billable resource, e.g. `llm.tokens.input` (master plan §11).

    Partitioned by month on `occurred_at`, so the key includes it.
    """

    __tablename__ = "usage_events"
    __table_args__ = (
        Index("ix_usage_events_organization_id_occurred_at", "organization_id", "occurred_at"),
        CheckConstraint("quantity >= 0", name="quantity_non_negative"),
        {"postgresql_partition_by": "RANGE (occurred_at)"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    occurred_at: Mapped[datetime] = mapped_column(primary_key=True, default=_utc_now)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"))
    meter: Mapped[str] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(Numeric)
    unit: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
