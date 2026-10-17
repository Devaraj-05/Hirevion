"""The report document (SP-17; ADR-0023): data, not markup. A report is sections of blocks, built
once by `hirevion_core.reports.*`; the web's `ReportView` and the PDF's HTML renderer both read it,
so a section has one source and the PDF can't show what the web view doesn't.

Blocks (every cell is already formatted text):

- `{"type": "text", "text", "tone": "normal" | "muted"}`
- `{"type": "list", "items": [str]}`
- `{"type": "facts", "rows": [{"label", "value"}]}`
- `{"type": "table", "caption", "columns": [str], "rows": [[str]]}`
- `{"type": "quotes", "items": [{"text", "source"}]}`
- `{"type": "notice", "tone": "info" | "warning", "text"}`
- `{"type": "code", "caption", "language", "text"}`

A section says whether it holds anything: `populated`, `empty` (nothing happened, said in its
note) or `pending` (waiting for something that doesn't exist yet, such as SP-16's coding).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

Block = dict[str, Any]
Section = dict[str, Any]
Document = dict[str, Any]
SectionStatus = Literal["populated", "empty", "pending"]
SCHEMA = 1
DASH = "—"


def text(value: str, *, muted: bool = False) -> Block:
    return {"type": "text", "text": value, "tone": "muted" if muted else "normal"}


def bullets(items: Iterable[str]) -> Block:
    return {"type": "list", "items": [item for item in items]}


def facts(rows: Iterable[tuple[str, str | None]]) -> Block:
    return {
        "type": "facts",
        "rows": [{"label": label, "value": value if value else DASH} for label, value in rows],
    }


def table(caption: str, columns: Sequence[str], rows: Iterable[Sequence[str | None]]) -> Block:
    return {
        "type": "table",
        "caption": caption,
        "columns": list(columns),
        "rows": [[cell if cell not in (None, "") else DASH for cell in row] for row in rows],
    }


def quotes(items: Iterable[tuple[str, str]]) -> Block:
    """`(quote, where it was said)`."""
    return {
        "type": "quotes",
        "items": [{"text": quote, "source": source} for quote, source in items],
    }


def notice(value: str, *, warning: bool = False) -> Block:
    return {"type": "notice", "tone": "warning" if warning else "info", "text": value}


def code(source: str, *, language: str | None = None, caption: str = "") -> Block:
    return {"type": "code", "caption": caption, "language": language, "text": source}


def _has_content(block: Block) -> bool:
    kind = block["type"]
    if kind in ("text", "notice", "code"):
        return bool(block["text"].strip())
    if kind == "list":
        return bool(block["items"])
    if kind == "facts":
        return any(row["value"] != DASH for row in block["rows"])
    if kind == "table":
        return bool(block["rows"])
    if kind == "quotes":
        return bool(block["items"])
    return False


def section(
    key: str,
    title: str,
    blocks: Sequence[Block],
    *,
    pending: bool = False,
    empty: bool = False,
    note: str | None = None,
) -> Section:
    """A section; `note` says why it is empty or pending."""
    status: SectionStatus
    if pending:
        status = "pending"
    elif empty:
        status = "empty"
    elif any(_has_content(block) for block in blocks if block["type"] != "notice"):
        status = "populated"
    else:
        status = "empty"
    return {"key": key, "title": title, "status": status, "note": note, "blocks": list(blocks)}


def document(
    kind: str,
    title: str,
    subtitle: str,
    sections: Sequence[Section],
    *,
    audience: str = "internal",
    subject: dict[str, str | None] | None = None,
    generated_at: datetime | None = None,
) -> Document:
    return {
        "schema_version": SCHEMA,
        "kind": kind,
        "title": title,
        "subtitle": subtitle,
        "audience": audience,
        "confidential": audience == "internal",
        "generated_at": (generated_at or datetime.now(UTC)).astimezone(UTC).isoformat(),
        "subject": subject or {},
        "sections": list(sections),
    }


def digest(doc: Document) -> str:
    """SHA-256 of the document, so an export can be shown to match what was on screen."""
    payload = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


# Formatting that every report shares.


def clock(ms: int | None) -> str:
    """A time within the interview: 1:02 or 1:02:03."""
    if ms is None:
        return DASH
    seconds = max(0, int(ms // 1000))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def when(moment: datetime | None, tz: str | None = None) -> str:
    """A date and time in the interview's own time zone: 17 Oct 2026, 15:35 IST."""
    if moment is None:
        return DASH
    local = moment.astimezone(zone(tz))
    return f"{local.day} {local:%b %Y, %H:%M %Z}"


def day(moment: datetime | None, tz: str | None = None) -> str:
    if moment is None:
        return DASH
    local = moment.astimezone(zone(tz))
    return f"{local.day} {local:%b %Y}"


def score(value: float | None) -> str:
    return f"{value:.1f}" if value is not None else DASH


def minutes(delta_ms: int | None) -> str:
    if delta_ms is None:
        return DASH
    total = max(0, round(delta_ms / 60_000))
    return f"{total} min"


def label(value: str) -> str:
    """`knowledge_gaps` as "Knowledge gaps"."""
    return value.replace("_", " ").capitalize()
