from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, LargeBinary, Text, func
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from hirevion_core.db.base import Base, IdMixin, TenantMixin

AUTH_TOKEN_PURPOSES = ("set_password", "reset_password", "verify_email")


class AuthToken(IdMixin, TenantMixin, Base):
    """A single-use emailed link: set a first password, reset one, or verify a new email.
    Only the SHA-256 of the token is stored."""

    __tablename__ = "auth_tokens"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('set_password', 'reset_password', 'verify_email')", name="purpose"
        ),
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["users.organization_id", "users.id"],
            ondelete="CASCADE",
        ),
        Index("ix_auth_tokens_user_id", "user_id"),
    )

    user_id: Mapped[UUID]
    purpose: Mapped[str] = mapped_column(Text)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    new_email: Mapped[str | None] = mapped_column(CITEXT)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
