"""Identity settings (`HV_SESSION_*`, `HV_HIBP_ENABLED`, `HV_WEB_ORIGIN`, ...)."""

from __future__ import annotations

from datetime import timedelta

from pydantic_settings import BaseSettings, SettingsConfigDict

from hirevion_core.settings import repo_env_file


class IdentitySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HV_", extra="ignore")

    session_idle_minutes: int = 30
    session_absolute_hours: int = 12
    # Off in CI and tests: the bundled list still applies.
    hibp_enabled: bool = True
    # Where the links in emails point (the recruiter app).
    web_origin: str = "https://app.hirevion.localhost"
    reset_token_minutes: int = 30
    verify_token_hours: int = 24
    set_password_token_hours: int = 72
    lockout_threshold: int = 5
    lockout_base_seconds: int = 60
    lockout_max_seconds: int = 3600
    # How long a confirmed password unlocks sensitive changes (step-up, ADR-0014).
    step_up_minutes: int = 10

    @property
    def session_idle(self) -> timedelta:
        return timedelta(minutes=self.session_idle_minutes)

    @property
    def step_up_window(self) -> timedelta:
        return timedelta(minutes=self.step_up_minutes)

    @property
    def session_absolute(self) -> timedelta:
        return timedelta(hours=self.session_absolute_hours)


def load_identity_settings() -> IdentitySettings:
    return IdentitySettings(_env_file=repo_env_file())  # type: ignore[call-arg]
