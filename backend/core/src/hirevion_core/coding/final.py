"""A coding question's final code (SP-16): its latest submission, else the last draft the console
saved. The evaluator reviews it and the reports and integrity signals show it, so all of them ask
this one function and never disagree."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class FinalCode:
    question_id: UUID
    code: str
    language: str | None
    source: str
    """A submission's source (`submitted`, `time_limit`, `closed`), or `snapshot`."""
    submission_id: str | None
    at: datetime


def final_codes(submissions: Iterable[Any], snapshots: Iterable[Any]) -> dict[UUID, FinalCode]:
    """Each question's final code. Both inputs are oldest first; only code drafts count."""
    finals: dict[UUID, FinalCode] = {}
    for snapshot in snapshots:
        if getattr(snapshot, "kind", "code") != "code":
            continue
        finals[snapshot.question_id] = FinalCode(
            snapshot.question_id,
            snapshot.content,
            (snapshot.language or "").lower() or None,
            "snapshot",
            None,
            snapshot.created_at,
        )
    submitted: dict[UUID, FinalCode] = {}
    for item in submissions:
        submitted[item.question_id] = FinalCode(
            item.question_id,
            item.code,
            item.language,
            item.source,
            str(item.id),
            item.created_at,
        )
    return finals | submitted
