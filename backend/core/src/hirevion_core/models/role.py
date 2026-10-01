from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from hirevion_core.db.base import Base, IdMixin, TenantMixin, TimestampMixin


class Role(IdMixin, TenantMixin, TimestampMixin, Base):
    """A role in one organisation. System roles carry a `key` from the code catalogue
    (`hirevion_core.identity.permissions`) and can't be edited; custom roles have none and keep
    their permissions in `role_permissions`. Names are unique per organisation, ignoring case."""

    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("organization_id", "key"),
        UniqueConstraint("organization_id", "name"),
        UniqueConstraint("organization_id", "id"),
    )

    key: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(CITEXT)
    description: Mapped[str | None] = mapped_column(Text)
    system: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class RolePermission(Base):
    """A permission granted by a custom role. System roles' permissions live in code."""

    __tablename__ = "role_permissions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "role_id"],
            ["roles.organization_id", "roles.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(r"permission ~ '^[a-z_]+(\.[a-z_]+)+$'", name="permission"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    role_id: Mapped[UUID] = mapped_column(primary_key=True)
    permission: Mapped[str] = mapped_column(Text, primary_key=True)


class UserRole(Base):
    """A role granted to a user, within their organisation."""

    __tablename__ = "user_roles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["users.organization_id", "users.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "role_id"],
            ["roles.organization_id", "roles.id"],
            ondelete="CASCADE",
        ),
        Index("ix_user_roles_role_id", "role_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[UUID] = mapped_column(primary_key=True)
    role_id: Mapped[UUID] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
