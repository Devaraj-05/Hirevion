import pytest

from hirevion_core.outbox import stream_name


@pytest.mark.parametrize("topic", ["interview.completed", "proctor_event", "report-ready", "ab"])
def test_stream_names_are_prefixed(topic: str) -> None:
    assert stream_name(topic) == f"hv:events:{topic}"


@pytest.mark.parametrize("topic", ["", "a", "Interview", "1st", "has space", "a:b", "a" * 64])
def test_unsafe_topics_are_rejected(topic: str) -> None:
    with pytest.raises(ValueError, match="topic"):
        stream_name(topic)
