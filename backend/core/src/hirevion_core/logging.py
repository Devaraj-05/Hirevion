"""Structured logs that never carry personal data or secrets (master plan §11).

`configure_logging()` writes one JSON object per line to stdout, with the current trace and span
ids. `RedactingFilter` masks email addresses, phone numbers, Aadhaar and PAN numbers, tokens and
passwords in every message and traceback before any handler formats it.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime

from opentelemetry import trace

_CREDENTIAL_FIELDS = r"password|passwd|secret|token|api[_-]?key|access[_-]?key|client[_-]?secret"
_RULES: list[tuple[re.Pattern[str], str]] = [
    # key=value and "key": "value" pairs whose key names a secret
    (
        re.compile(rf'(?i)("?(?:{_CREDENTIAL_FIELDS})"?\s*[:=]\s*"?)[^"&\s,;}}]+'),
        r"\1[redacted-secret]",
    ),
    # credentials in URLs (scheme://user:password@host)
    (re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://[^:/\s@]+:)[^@\s/]+@"), r"\1[redacted-secret]@"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [redacted-token]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*"), "[redacted-token]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[redacted-email]"),
    # international numbers: +<country code> then 7-13 more digits, spaces or dashes allowed
    (re.compile(r"(?<![\w+])\+\d{1,3}(?:[ -]?\d){6,12}(?![\w-])"), "[redacted-phone]"),
    # Aadhaar: 12 digits, optionally grouped 4-4-4
    (re.compile(r"(?<![\w-])\d{4}[ -]?\d{4}[ -]?\d{4}(?![\w-])"), "[redacted-aadhaar]"),
    # Indian mobile numbers without a country code
    (re.compile(r"(?<![\w-])[6-9]\d{9}(?![\w-])"), "[redacted-phone]"),
    (re.compile(r"(?<![\w-])[A-Z]{5}\d{4}[A-Z](?![\w-])"), "[redacted-pan]"),
]
_PLAIN = logging.Formatter()


def redact(text: str) -> str:
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    """Replaces the record's message (and traceback) with a redacted, pre-formatted copy."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = redact(_PLAIN.formatException(record.exc_info))
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        context = trace.get_current_span().get_span_context()
        entry: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": format(context.trace_id, "032x") if context.is_valid else None,
            "span_id": format(context.span_id, "016x") if context.is_valid else None,
        }
        if record.exc_info or record.exc_text:
            entry["exc"] = record.exc_text or (
                self.formatException(record.exc_info) if record.exc_info else ""
            )
        return json.dumps(entry, ensure_ascii=False)


class _StdoutHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """The handler `configure_logging()` owns, so calling it again replaces rather than adds."""


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    root = logging.getLogger()
    for handler in [h for h in root.handlers if isinstance(h, _StdoutHandler)]:
        root.removeHandler(handler)
    handler = _StdoutHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter()
        if json_output
        else logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    handler.addFilter(RedactingFilter())
    root.addHandler(handler)
    root.setLevel(level)
