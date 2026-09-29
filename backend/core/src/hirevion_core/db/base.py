"""The declarative base and the column conventions every table follows.

- Keys are UUIDv7 (`IdMixin`); times are UTC `timestamptz` (`TimestampMixin`).
- Tenant tables carry `organization_id` (`TenantMixin`) and a row-level security policy, which
  the migrations add with `hirevion_core.db.rls.tenant_policy_sql`.
- Constraint and index names are deterministic, so the migrations can name them explicitly.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from hirevion_core.ids import uuid7

NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {datetime: DateTime(timezone=True)}  # noqa: RUF012


class IdMixin:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class TenantMixin:
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
