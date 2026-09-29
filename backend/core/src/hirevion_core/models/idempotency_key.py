from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, LargeBinary, SmallInteger, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hirevion_core.db.base import Base


class IdempotencyKey(Base):
    """A create request's key and, once it succeeded, its response.

    The natural key is the whole identity: who sent it (`scope`) and the key they chose. See
    `hirevion_core.idempotency`.
    """

    __tablename__ = "idempotency_keys"
    __table_args__ = (Index("ix_idempotency_keys_created_at", "created_at"),)

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    scope: Mapped[str] = mapped_column(Text, primary_key=True)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    fingerprint: Mapped[bytes] = mapped_column(LargeBinary)
    status_code: Mapped[int | None] = mapped_column(SmallInteger)
    response: Mapped[Any | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
