"""SMTP settings (`HV_SMTP_*`, `HV_MAIL_FROM`). Locally they point at Mailpit."""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from hirevion_core.settings import repo_env_file


class MailSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HV_", extra="ignore", hide_input_in_errors=True)

    smtp_host: str = "127.0.0.1"
    smtp_port: int = 1025
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_starttls: bool = False
    mail_from: str = "Hirevion <no-reply@hirevion.localhost>"


def load_mail_settings() -> MailSettings:
    return MailSettings(_env_file=repo_env_file())  # type: ignore[call-arg]
