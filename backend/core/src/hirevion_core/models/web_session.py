from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKeyConstraint, Index, LargeBinary, Text, func
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from hirevion_core.db.base import Base, IdMixin, TenantMixin


class WebSession(IdMixin, TenantMixin, Base):
    """A signed-in browser. Only the SHA-256 of its token and of its CSRF token are stored."""

    __tablename__ = "web_sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["users.organization_id", "users.id"],
            ondelete="CASCADE",
        ),
        Index("ix_web_sessions_user_id", "user_id"),
    )

    user_id: Mapped[UUID]
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    csrf_hash: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_seen_at: Mapped[datetime]
    expires_at: Mapped[datetime]
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    revoked_at: Mapped[datetime | None]
