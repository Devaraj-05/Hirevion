"""16-bit mono PCM helpers for the voice benchmark."""

from __future__ import annotations

import wave
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

Samples = NDArray[np.int16]


def frame_rms(samples: Samples) -> float:
    """Root-mean-square level of 16-bit samples, scaled to 0..1."""
    if samples.size == 0:
        return 0.0
    scaled = samples.astype(np.float64) / 32768.0
    return float(np.sqrt(np.mean(scaled * scaled)))


def split_frames(samples: Samples, sample_rate: int, frame_ms: int = 10) -> list[Samples]:
    """Equal-length frames; the last one is padded with silence."""
    size = sample_rate * frame_ms // 1000
    padded_length = -(-samples.size // size) * size
    padded = np.zeros(padded_length, dtype=np.int16)
    padded[: samples.size] = samples
    return [padded[start : start + size] for start in range(0, padded_length, size)]


def first_voiced_index(frames: Sequence[Samples], threshold: float) -> int | None:
    for index, frame in enumerate(frames):
        if frame_rms(frame) >= threshold:
            return index
    return None


def write_wav(path: Path, samples: Samples, sample_rate: int) -> None:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(sample_rate)
        out.writeframes(samples.astype("<i2").tobytes())


def read_wav(path: Path) -> tuple[Samples, int]:
    with wave.open(str(path), "rb") as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise ValueError("expected 16-bit mono PCM")
        rate = source.getframerate()
        data = source.readframes(source.getnframes())
    return np.frombuffer(data, dtype="<i2").astype(np.int16), rate
