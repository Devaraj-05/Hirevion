from pathlib import Path

import numpy as np
import pytest

from hirevion_voice_bench.audio import (
    first_voiced_index,
    frame_rms,
    read_wav,
    split_frames,
    write_wav,
)

RATE = 48_000


def tone(seconds: float, amplitude: float = 0.5) -> np.ndarray:
    t = np.arange(int(RATE * seconds)) / RATE
    return (amplitude * 32767 * np.sin(2 * np.pi * 440 * t)).astype(np.int16)


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(RATE * seconds), dtype=np.int16)


def test_frame_rms_is_zero_for_silence_and_high_for_tone() -> None:
    assert frame_rms(silence(0.01)) == 0.0
    assert frame_rms(tone(0.01)) == pytest.approx(0.5 / np.sqrt(2), rel=0.05)


def test_split_frames_makes_equal_10ms_frames_and_pads_the_last() -> None:
    frames = split_frames(silence(0.025), RATE, frame_ms=10)
    assert len(frames) == 3
    assert all(len(frame) == RATE // 100 for frame in frames)


def test_first_voiced_index_skips_leading_silence() -> None:
    frames = split_frames(np.concatenate([silence(0.05), tone(0.05)]), RATE, frame_ms=10)
    assert first_voiced_index(frames, threshold=0.02) == 5
    assert first_voiced_index(split_frames(silence(0.05), RATE), threshold=0.02) is None


def test_wav_round_trip(tmp_path: Path) -> None:
    samples = tone(0.1)
    path = tmp_path / "answer.wav"
    write_wav(path, samples, RATE)
    loaded, rate = read_wav(path)
    assert rate == RATE
    assert np.array_equal(loaded, samples)


def test_read_wav_rejects_stereo(tmp_path: Path) -> None:
    import wave

    path = tmp_path / "stereo.wav"
    with wave.open(str(path), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(b"\x00\x00" * 200)
    with pytest.raises(ValueError, match="mono"):
        read_wav(path)
