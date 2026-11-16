"""The detector adapter (C7-1): LiveKit frames in, the model's boxes out, snapshots as JPEG."""

import hashlib
import io
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from livekit import rtc
from PIL import Image

from hirevion_vision_agent.detector import (
    MODEL,
    MODEL_SHA256,
    MediaPipeDetector,
    jpeg,
    rgb_from_frame,
    to_detections,
)
from hirevion_vision_agent.watch import Detection

DESKTOP_MODEL = (
    Path(__file__).resolve().parents[3]
    / "ai-interviewer-desktop"
    / "public"
    / "models"
    / "efficientdet_lite2.tflite"
)


def test_the_bundled_model_is_the_desktops_placement_model() -> None:
    """One model for the placement check and the interview: the same file, checked by hash."""
    ours = hashlib.sha256(MODEL.read_bytes()).hexdigest()
    assert ours == MODEL_SHA256
    assert hashlib.sha256(DESKTOP_MODEL.read_bytes()).hexdigest() == MODEL_SHA256


def test_a_livekit_frame_becomes_rgb_pixels() -> None:
    rgba = bytes([10, 20, 30, 255, 40, 50, 60, 255, 70, 80, 90, 255, 1, 2, 3, 255])
    frame = rtc.VideoFrame(2, 2, rtc.VideoBufferType.RGBA, rgba)
    pixels = rgb_from_frame(frame)
    assert pixels.shape == (2, 2, 3)
    assert pixels[0, 1].tolist() == [40, 50, 60]
    assert pixels.flags["C_CONTIGUOUS"]


def test_the_models_answer_becomes_detections() -> None:
    found = SimpleNamespace(
        categories=[SimpleNamespace(category_name="cell phone", score=0.71)],
        bounding_box=SimpleNamespace(origin_x=300, origin_y=400, width=60, height=110),
    )
    empty = SimpleNamespace(categories=[], bounding_box=None)
    result = SimpleNamespace(detections=[found, empty])
    assert to_detections(result) == [Detection("cell phone", 0.71, 300, 400, 60, 110)]


def test_a_missing_model_is_named_at_start(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="vision model"):
        MediaPipeDetector(tmp_path / "absent.tflite")


def test_a_snapshot_is_a_jpeg_of_the_frame() -> None:
    pixels = np.zeros((90, 160, 3), dtype=np.uint8)
    pixels[:, :80] = (200, 30, 30)
    data = jpeg(pixels)
    assert data[:2] == b"\xff\xd8"
    with Image.open(io.BytesIO(data)) as image:
        assert image.size == (160, 90)


def test_the_real_model_loads_and_finds_nothing_in_a_blank_picture() -> None:
    detector = MediaPipeDetector()
    try:
        assert detector.detect(np.full((360, 640, 3), 127, dtype=np.uint8)) == []
    finally:
        detector.close()
