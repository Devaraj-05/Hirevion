from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hirevion_core.db.base import Base, IdMixin, TenantMixin, TimestampMixin

DOCUMENT_KINDS = ("jd", "resume", "archive")
DOCUMENT_STATUSES = (
    "uploaded",
    "scanning",
    "extracting",
    "ocr",
    "parsing",
    "parsed",
    "quarantined",
    "failed",
)
# A document in one of these is done; the rest are still on their way through the pipeline.
FINAL_STATUSES = ("parsed", "quarantined", "failed")


class Document(IdMixin, TenantMixin, TimestampMixin, Base):
    """An uploaded or pasted job description or resume, and how far the pipeline got with it
    (ADR-0015). The file lives in blob storage; `text` is the extracted, normalised (and, for
    resumes, masked) text, and `extraction` the parse."""

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "job_id"], ["jobs.organization_id", "jobs.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["organization_id", "candidate_id"], ["candidates.organization_id", "candidates.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "parent_id"], ["documents.organization_id", "documents.id"]
        ),
        Index("ix_documents_organization_id_sha256", "organization_id", "sha256"),
        CheckConstraint(f"kind IN ({', '.join(repr(k) for k in DOCUMENT_KINDS)})", name="kind"),
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in DOCUMENT_STATUSES)})", name="status"
        ),
        Index("ix_documents_job_id_created_at", "job_id", "created_at"),
    )

    kind: Mapped[str] = mapped_column(Text)
    job_id: Mapped[UUID | None]
    # The candidate a resume became, and the ZIP archive it came out of.
    candidate_id: Mapped[UUID | None] = mapped_column(index=True)
    parent_id: Mapped[UUID | None] = mapped_column(index=True)
    filename: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(Text)
    size: Mapped[int] = mapped_column(BigInteger, server_default=sql_text("0"))
    sha256: Mapped[str | None] = mapped_column(Text)
    blob_path: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="uploaded")
    error_code: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, server_default=sql_text("0"))
    text: Mapped[str | None] = mapped_column(Text)
    pages: Mapped[int | None] = mapped_column(Integer)
    flags: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    extraction: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_by: Mapped[UUID | None]
