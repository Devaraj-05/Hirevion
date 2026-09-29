"""API process settings (`HV_API_*`), read from the environment and the repository's `.env`."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

from hirevion_core.settings import repo_env_file


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HV_API_", extra="ignore")

    # Host names the API answers to (without port); anything else gets 400 host-not-allowed.
    allowed_hosts: str = "api.hirevion.localhost,app.hirevion.localhost,localhost,127.0.0.1"
    # Proxies whose X-Forwarded-For is believed (Caddy reaches `hv api` from loopback).
    trusted_proxies: str = "127.0.0.1"
    max_body_bytes: int = 1_048_576
    # Requests per window per client IP, across the whole API.
    ip_rate_limit: int = 600
    ip_rate_window_seconds: int = 60
    docs_enabled: bool = True

    @property
    def hosts(self) -> frozenset[str]:
        return frozenset(_split(self.allowed_hosts))

    @property
    def proxies(self) -> list[str]:
        return _split(self.trusted_proxies)


def _split(value: str) -> list[str]:
    return [item.strip().lower() for item in value.split(",") if item.strip()]


def load_api_settings() -> ApiSettings:
    return ApiSettings(_env_file=repo_env_file())  # type: ignore[call-arg]
