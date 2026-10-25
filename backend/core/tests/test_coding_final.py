"""One answer to "what is this coding question's final code?" for the evaluator, the reports and the
signals; the languages the console offers and the submission accepts; the report's and the
candidate draft's wording (SP-16 code review)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from hirevion_core.coding.console import offered_languages
from hirevion_core.coding.final import final_codes
from hirevion_core.models.coding import CODING_LANGUAGES
from hirevion_core.reports.coding import question_line
from hirevion_core.reports.visible import coding_feedback

AT = datetime(2026, 10, 23, 10, 0, tzinfo=UTC)


def row(question, **fields):  # type: ignore[no-untyped-def]
    return SimpleNamespace(question_id=question, id=uuid4(), **fields)


def test_the_latest_submission_is_the_final_code() -> None:
    q = uuid4()
    submissions = [
        row(q, code="old", language="python", source="submitted", created_at=AT),
        row(q, code="new", language="javascript", source="time_limit", created_at=AT),
    ]
    snapshots = [row(q, content="draft", language="python", created_at=AT + timedelta(1))]
    [final] = final_codes(submissions, snapshots).values()
    assert (final.code, final.language, final.source) == ("new", "javascript", "time_limit")
    assert final.submission_id == str(submissions[1].id)


def test_without_a_submission_the_last_saved_draft_is_the_final_code() -> None:
    q, other = uuid4(), uuid4()
    snapshots = [
        row(q, content="first", language="python", created_at=AT),
        row(q, content="second", language="Python", created_at=AT + timedelta(minutes=1)),
        row(other, content="x", language=None, created_at=AT),
    ]
    finals = final_codes([], snapshots)
    assert finals[q].code == "second" and finals[q].source == "snapshot"
    assert finals[q].submission_id is None and finals[q].at == AT + timedelta(minutes=1)
    assert set(finals) == {q, other}


def test_the_console_and_the_submission_offer_the_same_languages() -> None:
    assert offered_languages(["Python", "sql"]) == ["python", "sql"]
    # A question whose languages aren't supported offers all four rather than none.
    assert offered_languages(["java"]) == list(CODING_LANGUAGES)
    assert offered_languages([]) == list(CODING_LANGUAGES)


def test_the_reports_line_never_prints_a_missing_estimate() -> None:
    scored = {"status": "scored", "score": 7.5, "criteria": {"time_complexity": {"estimate": None}}}
    assert question_line(scored) == "7.5"
    estimated = {
        "status": "scored",
        "score": 7.5,
        "criteria": {"time_complexity": {"estimate": "O(n)"}},
    }
    assert question_line(estimated) == "7.5, estimated O(n) time"
    assert question_line({"status": "no_code", "score": 0.0}) == "No code was given"
    assert question_line({}) is None


def test_the_candidates_draft_says_only_what_happened() -> None:
    assert coding_feedback({"status": "scored"}, asked=True) == (
        "Thank you for working through the coding question. Your code was reviewed after the "
        "interview."
    )
    assert coding_feedback({"status": "no_code"}, asked=True) == (
        "Thank you for your time on the coding question; there was no code to review."
    )
    assert coding_feedback({}, asked=True) == "Thank you for working through the coding question."
    assert coding_feedback({}, asked=False) == "There was no coding assessment in this interview."
