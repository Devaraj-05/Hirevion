from __future__ import annotations

from uuid import UUID

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from hirevion_core.db.base import Base, IdMixin


class Skill(IdMixin, Base):
    """A skill in the shared taxonomy (ADR-0015). Every organisation reads the same list; it
    changes only by migration, so it carries no `organization_id` and the app may only read it."""

    __tablename__ = "skills"

    name: Mapped[str] = mapped_column(CITEXT, unique=True)
    category: Mapped[str] = mapped_column(Text)


class SkillAlias(Base):
    """Another way job descriptions and resumes write a skill (`js` for JavaScript)."""

    __tablename__ = "skill_aliases"

    alias: Mapped[str] = mapped_column(CITEXT, primary_key=True)
    skill_id: Mapped[UUID] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True)
