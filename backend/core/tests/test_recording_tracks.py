"""Track names, formats and blob names (SP-12; `docs/api/contracts/recordings.md`)."""

from uuid import UUID

import pytest

from hirevion_core.recordings import tracks
from hirevion_core.storage.paths import interview_blob


@pytest.mark.parametrize("track", ["screen-1", "screen-2", "screen-8", "camera", "mic"])
def test_known_tracks(track: str) -> None:
    assert tracks.is_track(track)


@pytest.mark.parametrize(
    "track", ["screen", "screen-0", "screen-9", "screen-10", "Camera", "audio", "../mic", "mic "]
)
def test_unknown_tracks(track: str) -> None:
    assert not tracks.is_track(track)
    with pytest.raises(ValueError, match="track"):
        tracks.kind(track)


@pytest.mark.parametrize(
    ("track", "kind", "folder"),
    [
        ("screen-1", "screen", "screen"),
        ("screen-3", "screen", "screen"),
        ("camera", "camera", "camera"),
        ("mic", "mic", "audio"),
    ],
)
def test_kinds_and_section_85_folders(track: str, kind: str, folder: str) -> None:
    assert tracks.kind(track) == kind
    assert tracks.folder(track) == folder


def test_tracks_sort_screens_then_camera_then_mic() -> None:
    names = ["mic", "camera", "screen-2", "screen-1"]
    assert sorted(names, key=tracks.track_order) == ["screen-1", "screen-2", "camera", "mic"]


def test_egress_tracks_sort_after_the_desktops_and_are_never_uploadable() -> None:
    names = ["third-eye-2", "conversation-audio-1", "mic", "third-eye-10", "third-eye-1"]
    assert sorted(names, key=tracks.track_order) == [
        "mic",
        "conversation-audio-1",
        "third-eye-1",
        "third-eye-2",
        "third-eye-10",
    ]
    assert not tracks.is_track("third-eye-1") and not tracks.is_track("conversation-audio-1")
    assert tracks.egress_track("third-eye", 3) == "third-eye-3"
    with pytest.raises(ValueError, match="Egress"):
        tracks.egress_track("screen", 1)
    with pytest.raises(ValueError, match="Egress"):
        tracks.egress_track("third-eye", 0)


@pytest.mark.parametrize(
    ("track", "container", "codec", "allowed"),
    [
        ("screen-1", "mp4", "h264", True),
        ("screen-1", "webm", "vp8", False),
        ("screen-2", "mp4", "aac", False),
        ("camera", "webm", "vp8", True),
        ("camera", "mp4", "h264", True),
        ("mic", "webm", "opus", True),
        ("mic", "mp4", "aac", True),
        ("mic", "mp4", "vp8", False),
        ("camera", "webm", "h264", False),
    ],
)
def test_container_and_codec_rules(track: str, container: str, codec: str, allowed: bool) -> None:
    assert tracks.format_allowed(track, container, codec) is allowed


def test_the_contract_limits() -> None:
    assert tracks.MAX_SEGMENT_BYTES == 50_000_000
    assert tracks.MAX_SEGMENT_MS == 60_000


@pytest.mark.parametrize(
    ("policy", "track", "recorded"),
    [
        ({}, "camera", True),
        ({"recording": {}}, "mic", True),
        ({"recording": {"camera": False}}, "camera", False),
        ({"recording": {"camera": False}}, "screen-1", True),
        ({"recording": {"screen": False}}, "screen-2", False),
        ({"recording": {"audio": False}}, "mic", False),
        ({"recording": {"audio": True}}, "mic", True),
    ],
)
def test_the_pinned_policy_decides_what_is_recorded(
    policy: dict[str, object], track: str, recorded: bool
) -> None:
    assert tracks.is_recorded(policy, track) is recorded


def test_expected_tracks_follow_the_policy() -> None:
    assert tracks.expected_tracks({}) == ["screen-1", "camera", "mic"]
    assert tracks.expected_tracks({"recording": {"camera": False, "audio": False}}) == ["screen-1"]


def test_blob_names_are_safe_paths_under_section_85() -> None:
    org, interview = UUID(int=1), UUID(int=2)
    for track in ("screen-1", "screen-8", "camera", "mic"):
        for name in (
            tracks.segment_filename(track, 17, "mp4"),
            tracks.assembled_filename(track, "webm"),
            tracks.timeline_filename(track),
        ):
            path = interview_blob(org, interview, tracks.folder(track), name)  # must not raise
            assert str(path).startswith(f"{org}/interviews/{interview}/")
    assert tracks.segment_filename("screen-1", 17, "mp4") == "screen-1-000017.mp4"
    assert tracks.assembled_filename("mic", "webm") == "mic-full.webm"
    assert tracks.timeline_filename("camera") == "camera-timeline.json"


def test_each_build_has_its_own_file_names() -> None:
    assert tracks.assembled_filename("screen-1", "mp4", "0a1b2c") == "screen-1-full-0a1b2c.mp4"
    assert tracks.timeline_filename("mic", "0a1b2c") == "mic-timeline-0a1b2c.json"
    with pytest.raises(ValueError):
        tracks.assembled_filename("mic", "webm", "../x")
    with pytest.raises(ValueError, match="segment"):
        tracks.segment_filename("screen-1", -1, "mp4")


def test_content_types() -> None:
    assert tracks.content_type("screen-1", "mp4") == "video/mp4"
    assert tracks.content_type("camera", "webm") == "video/webm"
    assert tracks.content_type("mic", "mp4") == "audio/mp4"
