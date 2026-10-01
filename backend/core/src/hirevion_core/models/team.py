from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, ForeignKeyConstraint, Index, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from hirevion_core.db.base import Base, IdMixin, TenantMixin, TimestampMixin


class Team(IdMixin, TenantMixin, TimestampMixin, Base):
    """A group of users who share work (PRD §9). A user limited to their teams sees only work
    owned by one of them (`hirevion_core.access.scope`). Archived rather than deleted."""

    __tablename__ = "teams"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "department_id"],
            ["departments.organization_id", "departments.id"],
        ),
        UniqueConstraint("organization_id", "name"),
        UniqueConstraint("organization_id", "id"),
    )

    name: Mapped[str] = mapped_column(CITEXT)
    description: Mapped[str | None] = mapped_column(Text)
    department_id: Mapped[UUID | None]
    archived_at: Mapped[datetime | None]


class TeamMember(Base):
    """A user's membership of a team, within their organisation."""

    __tablename__ = "team_members"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "team_id"],
            ["teams.organization_id", "teams.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["users.organization_id", "users.id"],
            ondelete="CASCADE",
        ),
        Index("ix_team_members_user_id", "user_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    team_id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
