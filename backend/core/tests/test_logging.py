"""Structured logs that never carry personal data or secrets (master plan §11)."""

import json
import logging
import sys
from collections.abc import Iterator

import pytest
from opentelemetry.sdk.trace import TracerProvider

from hirevion_core.logging import JsonFormatter, RedactingFilter, configure_logging, redact


@pytest.mark.parametrize(
    ("text", "hidden"),
    [
        ("mail priya.sharma@example.co.in now", "priya.sharma@example.co.in"),
        ("call +91 98765 43210 today", "98765 43210"),
        ("call +44 20 7946 0958", "7946 0958"),
        ("call 9876543210", "9876543210"),
        ("aadhaar 1234 5678 9012", "1234 5678 9012"),
        ("aadhaar 123456789012", "123456789012"),
        ("pan ABCDE1234F", "ABCDE1234F"),
        ("Authorization: Bearer abc.def-ghi", "abc.def-ghi"),
        ("token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl", "eyJzdWIiOiIxIn0"),
        ("password=hunter2&next=1", "hunter2"),
        ('{"password": "hunter2"}', "hunter2"),
        ("api_key: sk-live-123", "sk-live-123"),
        ("dsn postgresql+asyncpg://hirevion_app:s3cr3t@127.0.0.1:5432/hirevion", "s3cr3t"),
    ],
)
def test_personal_data_and_secrets_are_redacted(text: str, hidden: str) -> None:
    cleaned = redact(text)
    assert hidden not in cleaned
    assert "[redacted" in cleaned


@pytest.mark.parametrize(
    "text",
    [
        "org 01920000-0000-7000-8000-000000000000",
        "took 1234 ms, seq 20 of 1234567",
        "at 2026-09-29T10:30:00.123456+00:00",
        "status 503 from 127.0.0.1:8000",
        "epoch 1727608200123",
    ],
)
def test_ordinary_values_survive(text: str) -> None:
    assert redact(text) == text


def record(message: str, *args: object, exc_info: object = None) -> logging.LogRecord:
    return logging.LogRecord(
        "hirevion.test",
        logging.INFO,
        __file__,
        1,
        message,
        args,
        exc_info,  # type: ignore[arg-type]
    )


def test_json_lines_carry_the_trace_context() -> None:
    line = json.loads(JsonFormatter().format(record("hello %s", "world")))
    assert line["message"] == "hello world"
    assert line["level"] == "INFO"
    assert line["logger"] == "hirevion.test"
    assert line["ts"].endswith("+00:00")
    assert line["trace_id"] is None

    tracer = TracerProvider().get_tracer("test")
    with tracer.start_as_current_span("work") as span:
        line = json.loads(JsonFormatter().format(record("inside")))
    context = span.get_span_context()
    assert line["trace_id"] == format(context.trace_id, "032x")
    assert line["span_id"] == format(context.span_id, "016x")


def test_exceptions_are_included() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        line = json.loads(JsonFormatter().format(record("failed", exc_info=sys.exc_info())))
    assert "ValueError: boom" in line["exc"]


def test_the_filter_redacts_after_formatting() -> None:
    entry = record("user %s signed in", "priya@example.com")
    assert RedactingFilter().filter(entry) is True
    assert entry.getMessage() == "user [redacted-email] signed in"


@pytest.fixture
def restore_root_logger() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.mark.usefixtures("restore_root_logger")
def test_configure_logging_writes_redacted_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json_output=True)
    logging.getLogger("hirevion.test").warning("mail %s", "priya@example.com")
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["message"] == "mail [redacted-email]"
    assert line["level"] == "WARNING"
