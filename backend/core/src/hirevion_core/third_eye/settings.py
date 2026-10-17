"""The third eye's settings (`HV_*` in the root `.env`)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from hirevion_core.settings import repo_env_file


def _default_egress_dir() -> Path:
    env = repo_env_file()
    root = env.parent if env is not None else Path.cwd()
    return root / "infrastructure" / "local" / "egress"


class ThirdEyeSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HV_", extra="ignore", hide_input_in_errors=True)

    third_eye_url: str = "https://eye.hirevion.localhost"
    """Where the phone page is served; the QR code's URL starts with it. Through the development
    tunnel it is the tunnel's `https://….trycloudflare.com` address."""
    third_eye_livekit_url: str | None = None
    """What the phone connects to. Unset: the phone page's own origin, which proxies LiveKit's
    `/rtc` (both local Caddy sites do), so one HTTPS origin serves the page and the signalling."""
    egress_output: Literal["local", "azure", "off"] = "local"
    """`local`: LiveKit's Egress writes into a directory shared with this process (a Docker
    volume), and the media worker moves each file into blob storage. `azure`: Egress uploads
    straight to the blob container. `off`: nothing is recorded by Egress."""
    egress_local_dir: Path = _default_egress_dir()
    """The shared directory as this process sees it (`local`)."""
    egress_container_dir: str = "/out"
    """The same directory as the Egress container sees it (`local`)."""


def load_third_eye_settings() -> ThirdEyeSettings:
    return ThirdEyeSettings(_env_file=repo_env_file())  # type: ignore[call-arg]
