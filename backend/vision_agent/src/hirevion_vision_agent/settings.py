"""Typed settings for the vision agent, read from the environment or the root .env."""

from __future__ import annotations

from pydantic import PositiveInt, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from hirevion_core.interview_session.media import VISION_AGENT_NAME
from hirevion_core.settings import repo_env_file


class VisionSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)

    livekit_url: str = "ws://127.0.0.1:7880"
    livekit_api_key: str
    livekit_api_secret: SecretStr
    # The name the API dispatches the vision agent to (explicit dispatch only).
    hv_vision_agent_name: str = VISION_AGENT_NAME
    # Interviews one worker watches before LiveKit sends it no more (each takes about 0.4 of a
    # CPU core at 2 frames a second).
    hv_vision_max_sessions: PositiveInt = 4


def load_settings() -> VisionSettings:
    # pydantic-settings fills the fields from the environment and _env_file; mypy only sees the
    # field-based __init__ that pydantic's dataclass transform declares.
    return VisionSettings(_env_file=repo_env_file())  # type: ignore[call-arg]
