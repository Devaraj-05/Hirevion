from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hirevion_core.db.base import Base
from hirevion_core.ids import uuid7


class AiInvocation(Base):
    """One AI call, with the PRD §79 governance fields, usage, latency and cost.

    Partitioned by month on `occurred_at`. Rows are written by `hirevion_core.ai.Recorder` in
    their own transaction and never changed.
    """

    __tablename__ = "ai_invocations"
    __table_args__ = (
        Index("ix_ai_invocations_organization_id_occurred_at", "organization_id", "occurred_at"),
        CheckConstraint(
            "service IN ('llm', 'embedding', 'stt', 'tts', 'vision', 'ocr')", name="service"
        ),
        CheckConstraint("status IN ('ok', 'error')", name="status"),
        {"postgresql_partition_by": "RANGE (occurred_at)"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    occurred_at: Mapped[datetime] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"))
    service: Mapped[str] = mapped_column(Text)
    purpose: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    model_version: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    rubric_version: Mapped[str | None] = mapped_column(Text)
    evaluation_version: Mapped[str | None] = mapped_column(Text)
    input_refs: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    output: Mapped[Any | None] = mapped_column(JSONB)
    input_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    audio_seconds: Mapped[Decimal] = mapped_column(Numeric, server_default=text("0"))
    characters: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    latency_ms: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric)
    status: Mapped[str] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(Text)
