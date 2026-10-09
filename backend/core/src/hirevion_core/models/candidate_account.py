from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from hirevion_core.db.base import Base, IdMixin, TenantMixin, TimestampMixin

CANDIDATE_ACCOUNT_STATUSES = ("invited", "active", "disabled")
CANDIDATE_TOKEN_PURPOSES = ("set_password", "reset_password")


class CandidateAccount(IdMixin, TenantMixin, TimestampMixin, Base):
    """A candidate's sign-in for the desktop app and the portal (PRD §8, §28): one per candidate
    per organisation, created by their first invitation and `invited` until they set a
    password."""

    __tablename__ = "candidate_accounts"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "candidate_id"),
        UniqueConstraint("organization_id", "email"),
        ForeignKeyConstraint(
            ["organization_id", "candidate_id"],
            ["candidates.organization_id", "candidates.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('invited', 'active', 'disabled')",
            name="status",
        ),
        Index("ix_candidate_accounts_email", "email"),
    )

    candidate_id: Mapped[UUID]
    email: Mapped[str] = mapped_column(CITEXT)
    name: Mapped[str] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(Text, server_default="en-IN")
    status: Mapped[str] = mapped_column(Text, server_default="invited")
    password_hash: Mapped[str | None] = mapped_column(Text)
    password_changed_at: Mapped[datetime | None]
    email_verified_at: Mapped[datetime | None]


class CandidateToken(IdMixin, TenantMixin, Base):
    """A single-use emailed link for a candidate account: set the first password, or reset it.
    Only the token's SHA-256 is stored."""

    __tablename__ = "candidate_tokens"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "account_id"],
            ["candidate_accounts.organization_id", "candidate_accounts.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("purpose IN ('set_password', 'reset_password')", name="purpose"),
        Index("ix_candidate_tokens_account_id", "account_id"),
    )

    account_id: Mapped[UUID]
    purpose: Mapped[str] = mapped_column(Text)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
