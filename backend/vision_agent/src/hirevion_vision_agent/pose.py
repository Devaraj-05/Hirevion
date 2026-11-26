"""Hands in the third eye's view (C7-2; PRD §58 "hands below frame"), from MediaPipe Pose
Landmarker Lite (Apache-2.0, bundled and checked by hash like the detector). Only the wrists'
visibility is used; landmarks stay in memory and nothing about the body is stored.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

from hirevion_vision_agent.detector import Pixels

MODEL = Path(__file__).parent / "models" / "pose_landmarker_lite.task"
MODEL_SHA256 = "59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a"
LEFT_WRIST, RIGHT_WRIST = 15, 16
VISIBLE = 0.5


class PoseEstimator(Protocol):
    def hands_visible(self, pixels: Pixels) -> bool | None: ...

    def close(self) -> None: ...


def _in_view(point: Any) -> bool:
    return (
        float(point.visibility) >= VISIBLE
        and 0.0 <= float(point.x) <= 1.0
        and 0.0 <= float(point.y) <= 1.0
    )


def hands_visible(landmarks: Sequence[Any]) -> bool | None:
    """Whether either wrist is in view; None without a pose (nothing to say)."""
    if len(landmarks) <= RIGHT_WRIST:
        return None
    return _in_view(landmarks[LEFT_WRIST]) or _in_view(landmarks[RIGHT_WRIST])


class MediaPipePose:
    def __init__(self, model: Path = MODEL) -> None:
        if not model.exists():
            raise FileNotFoundError(f"The pose model isn't at {model}")
        import mediapipe as mp
        from mediapipe.tasks import python as tasks
        from mediapipe.tasks.python import vision

        self._mp = mp
        options = vision.PoseLandmarkerOptions(
            base_options=tasks.BaseOptions(model_asset_path=str(model)),
            running_mode=vision.RunningMode.IMAGE,
            num_poses=1,
            min_pose_detection_confidence=0.5,
        )
        self._landmarker = vision.PoseLandmarker.create_from_options(options)

    def hands_visible(self, pixels: Pixels) -> bool | None:
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=pixels)
        result = self._landmarker.detect(image)
        if not result.pose_landmarks:
            return None
        return hands_visible(result.pose_landmarks[0])

    def close(self) -> None:
        self._landmarker.close()
