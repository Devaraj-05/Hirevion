import pytest

from hirevion_interview_agent.latency import LatencyCollector, percentile, summarize


def test_percentile_interpolates_between_ranks() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile(values, 50) == 3.0
    assert percentile(values, 95) == pytest.approx(4.8)
    assert percentile(values, 100) == 5.0
    assert percentile([7.0], 95) == 7.0


def test_percentile_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="empty"):
        percentile([], 50)


def test_collector_combines_stages_per_speech() -> None:
    collector = LatencyCollector()
    collector.record("s1", "eou", 0.6)
    collector.record("s1", "llm_ttft", 0.5)
    collector.record("s2", "eou", 0.7)
    collector.record("s1", "tts_ttfb", 0.2)
    completed = collector.completed()
    assert [turn.speech_id for turn in completed] == ["s1"]
    assert completed[0].total == pytest.approx(1.3)


def test_first_value_wins_for_repeated_stages() -> None:
    collector = LatencyCollector()
    for stage, first, later in (("eou", 0.5, 9.0), ("llm_ttft", 0.4, 9.0), ("tts_ttfb", 0.1, 9.0)):
        collector.record("s1", stage, first)
        collector.record("s1", stage, later)
    assert collector.completed()[0].total == pytest.approx(1.0)


def test_summarize_reports_percentiles_per_stage() -> None:
    collector = LatencyCollector()
    for index, eou in enumerate([0.5, 0.6, 0.7, 0.8]):
        speech = f"s{index}"
        collector.record(speech, "eou", eou)
        collector.record(speech, "llm_ttft", 0.5)
        collector.record(speech, "tts_ttfb", 0.2)
    summary = summarize(collector.completed())
    assert set(summary) == {"eou", "llm_ttft", "tts_ttfb", "total"}
    assert summary["eou"]["max"] == pytest.approx(0.8)
    assert summary["total"]["p50"] == pytest.approx(1.35)
    assert summary["llm_ttft"]["p95"] == pytest.approx(0.5)
