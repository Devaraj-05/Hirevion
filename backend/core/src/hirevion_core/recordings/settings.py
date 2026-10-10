"""Recording pipeline settings (`HV_FFMPEG_PATH` and friends). ffmpeg runs as a separate process;
where it isn't installed the media worker keeps tracks `assembly-pending` and says so."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

from hirevion_core.settings import repo_env_file


class RecordingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HV_", extra="ignore", hide_input_in_errors=True)

    # A name looked up on PATH, or a full path.
    ffmpeg_path: str = "ffmpeg"
    ffmpeg_timeout_seconds: int = 900
    # A track waits for segments whose upload URL was asked for this recently and aren't
    # acknowledged yet; after that they count as missing.
    recording_settle_seconds: int = 120
    recording_assembly_attempts: int = 5
    recording_poll_seconds: float = 15.0
    recording_monitor_seconds: float = 10.0


def load_recording_settings() -> RecordingSettings:
    return RecordingSettings(_env_file=repo_env_file())  # type: ignore[call-arg]
