"""Another voice in the candidate's audio (C7-2; PRD §59 and master plan §6.12 "detection of
additional speakers"): Deepgram labels each final transcript with its speaker; the candidate's
voice is the one that says most at the start, and another voice is flagged only when it keeps
talking, at most once a minute. A signal, never proof."""

from __future__ import annotations

from hirevion_interview_agent.voices import COOLDOWN_SECONDS, Heard, VoiceWatch

TWENTY = (
    "I have worked with Postgres and Redis for about three years in a payments team "
    "building ledgers every single day"
)


def warmed(label: str = "S0") -> VoiceWatch:
    watch = VoiceWatch()
    watch.heard(label, TWENTY, at=1.0)
    assert watch.candidate == label
    return watch


def test_the_candidate_is_the_voice_that_says_most_at_the_start() -> None:
    watch = VoiceWatch()
    # The interviewer's voice leaking back is heard first, briefly.
    assert watch.heard("S0", "tell me about yourself", at=0.5) is None
    assert watch.candidate is None
    assert watch.heard("S1", TWENTY, at=3.0) is None
    assert watch.candidate == "S1"


def test_the_candidates_own_voice_raises_nothing() -> None:
    watch = warmed()
    assert watch.heard("S0", "and with Redis as a cache", at=20.0) is None


def test_one_stray_label_is_not_another_voice() -> None:
    """Streaming diarisation can split one voice for a moment."""
    watch = warmed()
    assert watch.heard("S1", "use an index on that column please", at=30.0) is None


def test_another_voice_that_keeps_talking_is_flagged() -> None:
    watch = warmed()
    watch.heard("S1", "use an index on that", at=30.0)
    heard = watch.heard("S1", "and a covering one too", at=40.0)
    assert heard == Heard(at=40.0, speakers=2, words=10)


def test_a_few_words_from_another_voice_are_not_enough() -> None:
    watch = warmed()
    assert watch.heard("S1", "okay", at=30.0) is None
    assert watch.heard("S1", "sure thing", at=35.0) is None


def test_words_spread_over_more_than_a_minute_dont_add_up() -> None:
    watch = warmed()
    watch.heard("S1", "use an index on that", at=30.0)
    assert watch.heard("S1", "and a covering one", at=95.0) is None


def test_at_most_once_a_minute() -> None:
    watch = warmed()
    watch.heard("S1", "use an index on that", at=30.0)
    assert watch.heard("S1", "and a covering one too", at=40.0) is not None
    watch.heard("S1", "partition the table by month", at=50.0)
    assert watch.heard("S1", "and archive the old rows", at=60.0) is None
    later = 40.0 + COOLDOWN_SECONDS
    watch.heard("S2", "what about the cache layer", at=later - 5)
    assert watch.heard("S2", "use a write through cache", at=later) is not None


def test_no_speaker_label_tells_nothing() -> None:
    watch = warmed()
    assert watch.heard(None, "use an index on that column", at=30.0) is None
