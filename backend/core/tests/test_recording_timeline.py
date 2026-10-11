"""The timeline maths and the ffmpeg command line, as pure functions (SP-12)."""

from datetime import UTC, datetime, timedelta

import pytest

from hirevion_core.recordings.timeline import (
    SegmentInfo,
    build_timeline,
    concat_command,
    concat_list,
    find_gaps,
    to_server_time,
)

T0 = datetime(2026, 10, 12, 5, 0, 0, tzinfo=UTC)


def seg(seq: int, at_seconds: float, duration_ms: int = 10_000) -> SegmentInfo:
    return SegmentInfo(seq, T0 + timedelta(seconds=at_seconds), duration_ms)


def test_contiguous_segments_have_no_gaps() -> None:
    assert find_gaps([seg(0, 0), seg(1, 10), seg(2, 20)]) == []


def test_a_hole_between_segments_is_a_gap_with_its_times() -> None:
    (gap,) = find_gaps([seg(0, 0), seg(1, 10), seg(4, 40)])
    assert (gap.from_seq, gap.to_seq, gap.reason) == (2, 3, "missing")
    assert gap.from_time == T0 + timedelta(seconds=20)  # where the last good segment ended
    assert gap.to_time == T0 + timedelta(seconds=40)  # where the next one starts


def test_numbers_before_the_first_segment_are_a_gap_of_unknown_start() -> None:
    (gap,) = find_gaps([seg(3, 30), seg(4, 40)])
    assert (gap.from_seq, gap.to_seq) == (0, 2)
    assert gap.from_time is None
    assert gap.to_time == T0 + timedelta(seconds=30)


def test_a_segment_that_failed_its_hash_is_a_corrupt_gap_beside_missing_ones() -> None:
    gaps = find_gaps([seg(0, 0), seg(5, 50)], corrupt={2})
    assert [(g.from_seq, g.to_seq, g.reason) for g in gaps] == [
        (1, 1, "missing"),
        (2, 2, "corrupt"),
        (3, 4, "missing"),
    ]


def test_a_corrupt_last_segment_is_a_gap_at_the_end_of_the_track() -> None:
    (gap,) = find_gaps([seg(0, 0), seg(1, 10)], corrupt={2})
    assert (gap.from_seq, gap.to_seq, gap.reason) == (2, 2, "corrupt")
    assert gap.from_time == T0 + timedelta(seconds=20)
    assert gap.to_time is None


def test_segments_never_acknowledged_after_the_last_good_one_are_missing() -> None:
    gaps = find_gaps([seg(0, 0), seg(1, 10)], corrupt={3}, last_seq=5)
    assert [(g.from_seq, g.to_seq, g.reason, g.to_time) for g in gaps] == [
        (2, 2, "missing", None),
        (3, 3, "corrupt", None),
        (4, 5, "missing", None),
    ]


def test_the_stored_timeline_reports_the_missing_end() -> None:
    timeline = build_timeline("screen-1", "mp4", [seg(0, 0)], last_seq=2)
    assert [(g["from_seq"], g["to_seq"], g["to_time"]) for g in timeline["gaps"]] == [(1, 2, None)]


def test_segments_are_ordered_by_seq_whatever_the_input_order() -> None:
    assert find_gaps([seg(2, 20), seg(0, 0), seg(1, 10)]) == []


def test_the_map_gives_each_segment_its_offset_in_the_file() -> None:
    timeline = build_timeline("screen-1", "mp4", [seg(0, 0), seg(1, 10, 9_500), seg(3, 31)])
    assert timeline["track"] == "screen-1" and timeline["container"] == "mp4"
    assert timeline["started_at"] == T0.isoformat()
    assert [s["file_offset_ms"] for s in timeline["segments"]] == [0, 10_000, 19_500]
    assert timeline["duration_ms"] == 29_500
    assert timeline["ended_at"] == (T0 + timedelta(seconds=41)).isoformat()
    assert [(g["from_seq"], g["to_seq"]) for g in timeline["gaps"]] == [(2, 2)]


def test_file_time_maps_back_to_server_time_per_segment() -> None:
    timeline = build_timeline("camera", "webm", [seg(0, 0), seg(1, 10), seg(3, 35)])
    assert to_server_time(timeline, 0) == T0
    assert to_server_time(timeline, 4_000) == T0 + timedelta(seconds=4)
    assert to_server_time(timeline, 12_000) == T0 + timedelta(seconds=12)
    # 25 s into the file is 5 s into segment 3, which started at 35 s: the gap is skipped over.
    assert to_server_time(timeline, 25_000) == T0 + timedelta(seconds=40)


def test_each_segment_re_anchors_the_clock_so_drift_never_builds_up() -> None:
    # Real segments run a little off 10 s; the declared durations are what the file offsets use.
    timeline = build_timeline("mic", "webm", [seg(i, i * 10.03, 10_000) for i in range(6)])
    for i in range(6):
        offset = i * 10_000 + 2_000
        error = to_server_time(timeline, offset) - (T0 + timedelta(seconds=i * 10.03 + 2))
        assert abs(error) < timedelta(milliseconds=1)


def test_server_time_before_the_file_is_refused() -> None:
    timeline = build_timeline("mic", "webm", [seg(0, 0)])
    with pytest.raises(ValueError, match="offset"):
        to_server_time(timeline, -1)


def test_an_empty_track_has_no_timeline() -> None:
    with pytest.raises(ValueError, match="no segments"):
        build_timeline("mic", "webm", [])


def test_the_concat_list_quotes_names() -> None:
    assert concat_list(["seg-000000.mp4", "seg-000001.mp4"]) == (
        "file 'seg-000000.mp4'\nfile 'seg-000001.mp4'\n"
    )
    assert concat_list(["it's.mp4"]) == "file 'it'\\''s.mp4'\n"
    with pytest.raises(ValueError, match="newline"):
        concat_list(["a\nb.mp4"])


def test_the_ffmpeg_command_copies_without_re_encoding() -> None:
    command = concat_command("ffmpeg", "list.txt", "out.mp4", "mp4")
    assert command[0] == "ffmpeg"
    assert command[command.index("-f") + 1] == "concat"
    assert command[command.index("-i") + 1] == "list.txt"
    assert command[command.index("-c") + 1] == "copy"
    assert "-nostdin" in command and "-safe" not in command  # relative names only
    assert command[-1] == "out.mp4"
    assert "+faststart" in command  # an MP4 plays before it has fully downloaded
    assert "-movflags" not in concat_command("ffmpeg", "list.txt", "out.webm", "webm")


def test_ffmpeg_is_run_without_a_shell() -> None:
    command = concat_command("C:/tools/ffmpeg.exe", "list.txt", "out.mp4", "mp4")
    assert isinstance(command, list) and all(isinstance(part, str) for part in command)
