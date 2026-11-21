"""The analytics of one interview for the recruiter (owner, 2026-11-21: "i need to see the complete
analytics in the recruitment dashboard for that particular candidates"; ADR-0047)."""

from types import SimpleNamespace
from uuid import uuid4

from hirevion_core.reports.analytics import (
    Said,
    question_timing,
    severity_counts,
    skill_rows,
    speech,
)

Q1, Q2 = uuid4(), uuid4()


def said(seq: int, speaker: str, text: str, start: float, end: float, question=None) -> Said:
    return Said(seq, speaker, text, int(start * 1000), int(end * 1000), question)


TRANSCRIPT = [
    said(1, "ai", "Hello. What is a tuple?", 0, 6, Q1),
    said(2, "candidate", "Um, a tuple is an immutable sequence.", 9, 13, Q1),
    said(3, "candidate", "You know, it can be a dictionary key.", 13.5, 16, Q1),
    said(4, "ai", "What would you use Redis for?", 17, 20, Q2),
    said(5, "candidate", "Caching hot reads, uh, and rate limits.", 32, 36, Q2),
]


def test_speech_measures_time_pace_response_and_fillers() -> None:
    stats = speech(TRANSCRIPT)
    assert stats.candidate_ms == 10_500 and stats.ai_ms == 9_000
    assert stats.words == 22
    assert stats.words_per_minute == 126  # 22 words in 10.5 s
    # Each answer starts after the interviewer stops: 3 s, then 12 s.
    assert stats.response_ms == [3_000, 12_000]
    assert stats.median_response_ms == 7_500
    assert stats.long_pauses == 1  # over 10 s
    # Hesitation sounds only: "you know" is often just words (review, 2026-11-21).
    assert stats.fillers == {"um": 1, "uh": 1}
    assert stats.fillers_per_100_words == 9.1
    assert stats.candidate_share == 0.54


def test_an_answer_that_starts_before_the_question_ends_counts_as_no_wait() -> None:
    overlap = [
        said(1, "ai", "Tell me about it.", 0, 5, Q1),
        said(2, "candidate", "Sure thing.", 4, 6, Q1),
    ]
    assert speech(overlap).response_ms == [0]


def test_little_speech_has_no_pace_and_none_has_no_share() -> None:
    assert speech([said(1, "candidate", "Yes.", 0, 1, Q1)]).words_per_minute is None
    empty = speech([])
    assert empty.words == 0 and empty.candidate_share is None and empty.median_response_ms is None


def test_each_question_has_its_thinking_and_speaking_time() -> None:
    timing = question_timing(TRANSCRIPT)
    assert timing[Q1].thinking_ms == 3_000 and timing[Q1].speaking_ms == 6_500
    assert timing[Q1].words == 15 and timing[Q1].asked_ms == 0
    assert timing[Q2].thinking_ms == 12_000 and timing[Q2].speaking_ms == 4_000
    assert timing[Q2].asked_ms == 17_000


def test_a_question_without_an_answer_has_no_thinking_time() -> None:
    timing = question_timing([said(1, "ai", "Anything else?", 0, 2, Q1)])
    assert timing[Q1].thinking_ms is None and timing[Q1].speaking_ms == 0


def test_an_impossible_pace_is_not_shown() -> None:
    # Answers stored as only their last stretch of speech (before 2026-11-21's agent fix) give
    # paces no one speaks at: 450 words a minute on the owner's run.
    rushed = [said(1, "candidate", " ".join(["word"] * 100), 0, 12, Q1)]
    stats = speech(rushed)
    assert stats.words == 100 and stats.words_per_minute is None and stats.pace_unreliable
    assert not speech(TRANSCRIPT).pace_unreliable


def test_a_dash_is_not_a_word() -> None:
    assert speech([said(1, "candidate", "A B-tree index -- the usual - one", 0, 2, Q1)]).words == 6


def score(value: float) -> SimpleNamespace:
    return SimpleNamespace(ai=value, value=value)


def test_skill_scores_match_without_case_and_evaluation_only_skills_stay() -> None:
    coverage = [
        {
            "skill": "PostgreSQL",
            "required": True,
            "covered": True,
            "asked": 2,
            "answered": 2,
            "planned": 2,
            "dropped": False,
        },
    ]
    questions = [
        SimpleNamespace(skill="Kafka", status="answered"),
        SimpleNamespace(skill="Kafka", status="skipped"),
    ]
    rows = skill_rows(coverage, {"postgresql": score(7.5), "Kafka": score(4.0)}, questions)
    assert [(r["skill"], r["score"]) for r in rows] == [("PostgreSQL", 7.5), ("Kafka", 4.0)]
    assert rows[1] == {
        "skill": "Kafka",
        "required": False,
        "covered": True,
        "asked": 2,
        "answered": 1,
        "planned": 0,
        "dropped": False,
        "score": 4.0,
    }


def test_the_process_list_is_no_detection_and_dismissed_events_dont_count() -> None:
    events = [
        SimpleNamespace(id=1, event="PROCESS_INVENTORY", severity="INFO"),
        SimpleNamespace(id=2, event="VM_DETECTED", severity="INFO"),
        SimpleNamespace(id=3, event="PHONE_DETECTED", severity="CRITICAL"),
        SimpleNamespace(id=4, event="PHONE_DETECTED", severity="CRITICAL"),
    ]
    reviews = {4: SimpleNamespace(outcome="false_positive")}
    assert severity_counts(events, reviews) == {"INFO": 1, "WARNING": 0, "CRITICAL": 1}
