from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, LargeBinary, Text, func
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hirevion_core.db.base import Base, IdMixin, TenantMixin, TimestampMixin

# Master plan §6.3's requests; the data rights are the DPDP Act's (sections 11 to 14).
CANDIDATE_REQUEST_KINDS = (
    "reschedule",
    "support",
    "accommodation",
    "alternative_process",
    "data_access",
    "data_correction",
    "data_erasure",
    "grievance",
    "nomination",
    "consent_withdrawal",
)
CANDIDATE_REQUEST_STATUSES = ("open", "in_progress", "resolved", "declined")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class CandidateWebSession(IdMixin, TenantMixin, Base):
    """A candidate signed in to the portal (ADR-0022): ADR-0013's web session, for a candidate
    account. Only the SHA-256 of its token and of its CSRF token are stored."""

    __tablename__ = "candidate_web_sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "account_id"],
            ["candidate_accounts.organization_id", "candidate_accounts.id"],
            ondelete="CASCADE",
        ),
        Index("ix_candidate_web_sessions_account_id", "account_id"),
    )

    account_id: Mapped[UUID]
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    csrf_hash: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_seen_at: Mapped[datetime]
    expires_at: Mapped[datetime]
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    revoked_at: Mapped[datetime | None]


class CandidateRequest(IdMixin, TenantMixin, TimestampMixin, Base):
    """Something a candidate asked of the organisation from the portal (master plan §6.3), and
    what the organisation did about it."""

    __tablename__ = "candidate_requests"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "account_id"],
            ["candidate_accounts.organization_id", "candidate_accounts.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "candidate_id"],
            ["candidates.organization_id", "candidates.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "interview_id"],
            ["interviews.organization_id", "interviews.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "handled_by"], ["users.organization_id", "users.id"]
        ),
        CheckConstraint(_in("kind", CANDIDATE_REQUEST_KINDS), name="kind"),
        CheckConstraint(_in("status", CANDIDATE_REQUEST_STATUSES), name="status"),
        Index("ix_candidate_requests_account_id", "account_id"),
        Index("ix_candidate_requests_interview_id", "interview_id"),
        Index("ix_candidate_requests_status_created_at", "status", "created_at"),
    )

    account_id: Mapped[UUID]
    candidate_id: Mapped[UUID]
    interview_id: Mapped[UUID | None]
    kind: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="open")
    message: Mapped[str] = mapped_column(Text, server_default="")
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    response: Mapped[str | None] = mapped_column(Text)
    handled_by: Mapped[UUID | None]
    handled_at: Mapped[datetime | None]
