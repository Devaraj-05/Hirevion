"""Quotes are checked against the stored transcript (SP-10 Task 1; master plan §3.2(3))."""

from hirevion_core.evaluation.evidence import Quotable, Turn

ANSWER = Turn(
    seq=12,
    text="I would add an index on the join column, then run EXPLAIN ANALYZE to check the plan.",
    start_ms=83_000,
    end_ms=91_500,
    question_id="q1",
)
OTHER = Turn(
    seq=14,
    text="Partitioning by month keeps each table small — it also makes retention easy.",
    start_ms=120_000,
    end_ms=126_000,
    question_id="q2",
)


def test_a_quote_is_found_and_carries_its_turns_times() -> None:
    [item] = Quotable([ANSWER, OTHER]).verify(["add an index on the join column"])
    assert (item.seq, item.start_ms, item.end_ms, item.question_id) == (12, 83_000, 91_500, "q1")
    assert item.quote == "add an index on the join column"


def test_case_spacing_and_the_style_of_quotes_and_dashes_do_not_matter() -> None:
    quotable = Quotable([ANSWER, OTHER])
    assert quotable.verify(["RUN  explain analyze\nto check the plan"])
    assert quotable.verify(["it also makes retention easy"])
    assert quotable.verify(["small - it also makes"])  # the transcript's dash is an em dash
    assert quotable.verify(['"add an index on the join column..."'])  # quotes and ellipsis trimmed


def test_what_is_not_in_the_transcript_is_dropped() -> None:
    quotable = Quotable([ANSWER])
    assert quotable.verify(["I would shard the database across regions"]) == []
    assert quotable.verify(["add an index on the join column and cache it"]) == []


def test_tiny_quotes_prove_nothing() -> None:
    assert Quotable([ANSWER]).verify(["the", "an", "index"]) == []


def test_a_quote_must_sit_inside_one_turn() -> None:
    joined = "check the plan. Partitioning by month"
    assert Quotable([ANSWER, OTHER]).verify([joined]) == []


def test_scoping_to_a_question_ignores_other_questions_turns() -> None:
    quotable = Quotable([ANSWER, OTHER])
    assert quotable.verify(["Partitioning by month keeps each table small"], question_id="q1") == []
    assert quotable.verify(["Partitioning by month keeps each table small"], question_id="q2")


def test_duplicates_collapse_and_the_limit_applies() -> None:
    quotes = [
        "add an index on the join column",
        "ADD AN INDEX on the join column",
        "run EXPLAIN ANALYZE",
        "to check the plan",
        "I would add an index",
    ]
    found = Quotable([ANSWER]).verify(quotes, limit=3)
    assert [item.quote for item in found] == [
        "add an index on the join column",
        "run EXPLAIN ANALYZE",
        "to check the plan",
    ]
    assert found[0].as_json() == {
        "quote": "add an index on the join column",
        "seq": 12,
        "start_ms": 83_000,
        "end_ms": 91_500,
        "question_id": "q1",
    }
