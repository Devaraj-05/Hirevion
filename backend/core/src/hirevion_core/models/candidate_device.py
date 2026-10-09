from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hirevion_core.db.base import Base, IdMixin, TenantMixin


class CandidateDevice(IdMixin, TenantMixin, Base):
    """A device key a candidate signed in with (PRD §8 device binding): the RFC 7638
    thumbprint of its P-256 public key, which every token is bound to (`cnf.jkt`)."""

    __tablename__ = "candidate_devices"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("account_id", "jkt"),
        ForeignKeyConstraint(
            ["organization_id", "account_id"],
            ["candidate_accounts.organization_id", "candidate_accounts.id"],
            ondelete="CASCADE",
        ),
    )

    account_id: Mapped[UUID]
    jkt: Mapped[str] = mapped_column(Text)
    public_jwk: Mapped[dict[str, Any]] = mapped_column(JSONB)
    name: Mapped[str] = mapped_column(Text, server_default="")
    app: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    verified_at: Mapped[datetime | None]
    first_seen_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(server_default=func.now())
    revoked_at: Mapped[datetime | None]


class CandidateOtp(IdMixin, TenantMixin, Base):
    """A one-time code emailed to confirm a new device; its `id` is the challenge id."""

    __tablename__ = "candidate_otps"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "account_id"],
            ["candidate_accounts.organization_id", "candidate_accounts.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("attempts >= 0", name="attempts"),
        Index("ix_candidate_otps_account_id", "account_id"),
    )

    account_id: Mapped[UUID]
    jkt: Mapped[str] = mapped_column(Text)
    code_hash: Mapped[bytes] = mapped_column(LargeBinary)
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    sends: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    last_sent_at: Mapped[datetime]
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class CandidateRefreshToken(IdMixin, TenantMixin, Base):
    """One refresh token of a sign-in's family: rotated on every use, 8 hours at most from
    sign-in; using a spent one revokes the family."""

    __tablename__ = "candidate_refresh_tokens"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "account_id"],
            ["candidate_accounts.organization_id", "candidate_accounts.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "device_id"],
            ["candidate_devices.organization_id", "candidate_devices.id"],
            ondelete="CASCADE",
        ),
        Index("ix_candidate_refresh_tokens_family_id", "family_id"),
    )

    account_id: Mapped[UUID]
    device_id: Mapped[UUID]
    family_id: Mapped[UUID]
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    family_expires_at: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    used_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
