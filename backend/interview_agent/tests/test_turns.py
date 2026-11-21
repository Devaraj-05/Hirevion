"""An answer's time is from its first speech to its last (the owner's run of 2026-11-21: each
pause mid-answer moved its start, so answers were stored as only their last stretch of speech;
ADR-0047)."""

from datetime import UTC, datetime, timedelta

from hirevion_interview_agent.turns import SpeechWindow

T0 = datetime(2026, 11, 21, 10, 0, tzinfo=UTC)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def test_a_pause_mid_answer_never_moves_its_start() -> None:
    window = SpeechWindow()
    window.speaking(at(0))
    window.stopped(at(4))
    window.speaking(at(6))  # the candidate goes on after a pause
    window.stopped(at(15))
    assert window.take(at(16)) == (at(0), at(15))


def test_taking_the_window_starts_the_next_answer_afresh() -> None:
    window = SpeechWindow()
    window.speaking(at(0))
    window.stopped(at(3))
    window.take(at(4))
    window.speaking(at(20))
    assert window.take(at(25)) == (at(20), at(25))  # not stopped yet: up to now


def test_no_speech_heard_has_no_start() -> None:
    assert SpeechWindow().take(at(5)) == (None, at(5))


def test_speech_that_resumes_has_no_end_until_it_stops_again() -> None:
    # "Done answering" can take the window while the candidate still speaks (review, 2026-11-21).
    window = SpeechWindow()
    window.speaking(at(0))
    window.stopped(at(4))
    window.speaking(at(6))
    assert window.take(at(12)) == (at(0), at(12))


def test_a_stop_without_a_start_belongs_to_no_answer() -> None:
    window = SpeechWindow()
    window.stopped(at(13))  # the end of speech the last take() already counted
    window.speaking(at(40))
    assert window.take(at(45)) == (at(40), at(45))


def test_clearing_drops_a_sound_no_answer_came_from() -> None:
    # A cough during the question: speech the recogniser dropped mustn't start the next answer.
    window = SpeechWindow()
    window.speaking(at(30))
    window.stopped(at(31))
    window.clear()
    window.speaking(at(45))
    window.stopped(at(75))
    assert window.take(at(76)) == (at(45), at(75))
