"""The object detector the vision agent runs on the third eye's frames (C7-1).

MediaPipe's EfficientDet-Lite2 (int8, COCO labels, Apache-2.0): the same file as the desktop's
placement check (ADR-0042), bundled here and checked by hash. Only `person` and `cell phone`
are kept. It runs on the CPU (about 0.2 s a frame on an i5); the agent calls it in a thread.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from livekit import rtc
from numpy.typing import NDArray
from PIL import Image

from hirevion_vision_agent.watch import Detection

MODEL = Path(__file__).parent / "models" / "efficientdet_lite2.tflite"
MODEL_SHA256 = "b3f50554cb0ea559e90328845f7d9ba4d13c8bff372914d24e06bc8bb72fa896"
LABELS = ["person", "cell phone"]
MIN_SCORE = 0.3

Pixels = NDArray[np.uint8]


class Detector(Protocol):
    def detect(self, pixels: Pixels) -> list[Detection]: ...

    def close(self) -> None: ...


def rgb_from_frame(frame: rtc.VideoFrame) -> Pixels:
    """A LiveKit frame (any format) as a height x width x 3 RGB array for the detector and JPEG."""
    rgba = (
        frame if frame.type == rtc.VideoBufferType.RGBA else frame.convert(rtc.VideoBufferType.RGBA)
    )
    data = np.frombuffer(rgba.data, dtype=np.uint8)
    return np.ascontiguousarray(data.reshape(rgba.height, rgba.width, 4)[:, :, :3])


def to_detections(result: Any) -> list[Detection]:
    """MediaPipe's `ObjectDetectorResult` as plain detections (pixels of the analysed frame)."""
    found: list[Detection] = []
    for detection in result.detections:
        if not detection.categories or detection.bounding_box is None:
            continue
        category = detection.categories[0]
        box = detection.bounding_box
        found.append(
            Detection(
                category.category_name,
                float(category.score),
                float(box.origin_x),
                float(box.origin_y),
                float(box.width),
                float(box.height),
            )
        )
    return found


def jpeg(pixels: Pixels, quality: int = 80) -> bytes:
    """The snapshot kept as evidence."""
    buffer = io.BytesIO()
    Image.fromarray(pixels, "RGB").save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


class MediaPipeDetector:
    def __init__(self, model: Path = MODEL) -> None:
        if not model.exists():
            raise FileNotFoundError(f"The vision model isn't at {model}")
        import mediapipe as mp
        from mediapipe.tasks import python as tasks
        from mediapipe.tasks.python import vision

        self._mp = mp
        options = vision.ObjectDetectorOptions(
            base_options=tasks.BaseOptions(model_asset_path=str(model)),
            running_mode=vision.RunningMode.IMAGE,
            score_threshold=MIN_SCORE,
            max_results=10,
            category_allowlist=LABELS,
        )
        self._detector = vision.ObjectDetector.create_from_options(options)

    def detect(self, pixels: Pixels) -> list[Detection]:
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=pixels)
        return to_detections(self._detector.detect(image))

    def close(self) -> None:
        self._detector.close()
