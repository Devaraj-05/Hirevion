"""Hands out of the third eye's view (C7-2; PRD §58 "hands below frame"): from MediaPipe Pose's
wrists. Plain landmark numbers, never photos."""

from __future__ import annotations

from types import SimpleNamespace

from hirevion_vision_agent.pose import LEFT_WRIST, RIGHT_WRIST, hands_visible


def landmarks(left: float, right: float) -> list[SimpleNamespace]:
    points = [SimpleNamespace(x=0.5, y=0.5, visibility=0.99) for _ in range(33)]
    points[LEFT_WRIST] = SimpleNamespace(x=0.4, y=0.8, visibility=left)
    points[RIGHT_WRIST] = SimpleNamespace(x=0.6, y=0.8, visibility=right)
    return points


def test_a_visible_wrist_is_a_hand_in_view() -> None:
    assert hands_visible(landmarks(0.9, 0.1)) is True
    assert hands_visible(landmarks(0.1, 0.8)) is True


def test_both_wrists_hidden_is_hands_out_of_view() -> None:
    assert hands_visible(landmarks(0.2, 0.3)) is False


def test_a_wrist_outside_the_picture_is_not_visible() -> None:
    points = landmarks(0.95, 0.95)
    points[LEFT_WRIST] = SimpleNamespace(x=0.4, y=1.2, visibility=0.95)
    points[RIGHT_WRIST] = SimpleNamespace(x=0.6, y=1.1, visibility=0.95)
    assert hands_visible(points) is False


def test_no_pose_tells_nothing() -> None:
    assert hands_visible([]) is None


def test_the_bundled_pose_model_is_the_pinned_one() -> None:
    import hashlib

    from hirevion_vision_agent.pose import MODEL, MODEL_SHA256

    assert hashlib.sha256(MODEL.read_bytes()).hexdigest() == MODEL_SHA256


def test_the_real_model_loads_and_finds_no_one_in_an_empty_picture() -> None:
    import numpy as np

    from hirevion_vision_agent.pose import MediaPipePose

    pose = MediaPipePose()
    try:
        assert pose.hands_visible(np.full((360, 640, 3), 90, dtype=np.uint8)) is None
    finally:
        pose.close()


def test_a_missing_pose_model_is_named_at_start(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import pytest

    from hirevion_vision_agent.pose import MediaPipePose

    with pytest.raises(FileNotFoundError, match="pose model"):
        MediaPipePose(tmp_path / "absent.task")
