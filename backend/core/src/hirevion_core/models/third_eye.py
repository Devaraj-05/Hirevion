"""The third eye's pairings (SP-13, PRD §52; `docs/api/contracts/third-eye.md`)."""

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
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hirevion_core.db.base import Base, IdMixin, TenantMixin, TimestampMixin

PAIRING_STATUSES = ("issued", "redeemed", "connected", "disconnected", "revoked")
REVOKE_REASONS = ("replaced", "revoked", "interview-ended")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class ThirdEyePairing(IdMixin, TenantMixin, TimestampMixin, Base):
    """One phone paired as an interview's third camera, from the QR code to revocation.

    Only the SHA-256 of the pairing token (spent once, within two minutes) and of the device
    secret (what lets the phone rejoin after a lock) are stored. An interview has at most one
    pairing that isn't revoked."""

    __tablename__ = "third_eye_pairings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "interview_id"],
            ["interviews.organization_id", "interviews.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "candidate_id"],
            ["candidates.organization_id", "candidates.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "account_id"],
            ["candidate_accounts.organization_id", "candidate_accounts.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(_in("status", PAIRING_STATUSES), name="status"),
        CheckConstraint(
            f"revoke_reason IS NULL OR {_in('revoke_reason', REVOKE_REASONS)}",
            name="revoke_reason",
        ),
        CheckConstraint("(status = 'revoked') = (revoked_at IS NOT NULL)", name="revoked"),
        CheckConstraint("reconnects >= 0", name="reconnects"),
        Index("ix_third_eye_pairings_interview_id", "interview_id"),
        Index(
            "uq_third_eye_pairings_live",
            "interview_id",
            unique=True,
            postgresql_where=sql_text("revoked_at IS NULL"),
        ),
    )

    interview_id: Mapped[UUID]
    candidate_id: Mapped[UUID]
    # The candidate account whose desktop asked for it.
    account_id: Mapped[UUID | None]
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    device_hash: Mapped[bytes | None] = mapped_column(LargeBinary, unique=True)
    status: Mapped[str] = mapped_column(Text, server_default="issued")
    expires_at: Mapped[datetime]
    redeemed_at: Mapped[datetime | None]
    connected_at: Mapped[datetime | None]
    last_seen_at: Mapped[datetime | None]
    disconnected_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
    revoke_reason: Mapped[str | None] = mapped_column(Text)
    # The phone as it described itself (`platform`, a short user agent); never used to decide.
    device: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    # The camera track LiveKit reported (`width`, `height`, `fps`).
    video: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reconnects: Mapped[int] = mapped_column(Integer, server_default=sql_text("0"))
