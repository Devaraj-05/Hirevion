"""Connection settings shared by every backend service, read from the environment and the
repository's root `.env` (created by `uv run hv init-env`)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import quote

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Database roles. The application never connects as a superuser or a table owner, so
# row-level security always applies to it (ADR-0009).
APP_ROLE = "hirevion_app"
RELAY_ROLE = "hirevion_relay"
# Owns the sign-in lookup functions (no login, no row-level security bypass; ADR-0013).
AUTH_ROLE = "hirevion_auth"

Role = Literal["admin", "app", "relay"]


def repo_env_file() -> Path | None:
    """The root `.env` of the repository this code runs from, if there is one."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "MASTER_IMPLEMENTATION_PLAN.md").exists():
            env = parent / ".env"
            return env if env.exists() else None
    return None


class CoreSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)

    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_db: str = "hirevion"
    # The admin role runs migrations and creates the application roles.
    postgres_user: str
    postgres_password: SecretStr
    postgres_app_password: SecretStr
    postgres_relay_password: SecretStr

    valkey_host: str = "127.0.0.1"
    valkey_port: int = 6379
    valkey_password: SecretStr = SecretStr("")

    def database_url(self, role: Role, database: str | None = None) -> str:
        """An asyncpg SQLAlchemy URL for `role` on `database` (default `postgres_db`)."""
        user, password = {
            "admin": (self.postgres_user, self.postgres_password),
            "app": (APP_ROLE, self.postgres_app_password),
            "relay": (RELAY_ROLE, self.postgres_relay_password),
        }[role]
        secret = quote(password.get_secret_value(), safe="")
        name = database or self.postgres_db
        return (
            f"postgresql+asyncpg://{quote(user, safe='')}:{secret}"
            f"@{self.postgres_host}:{self.postgres_port}/{name}"
        )

    def valkey_url(self, database: int = 0) -> str:
        password = self.valkey_password.get_secret_value()
        auth = f":{quote(password, safe='')}@" if password else ""
        return f"redis://{auth}{self.valkey_host}:{self.valkey_port}/{database}"


def load_core_settings() -> CoreSettings:
    # pydantic-settings fills the fields from the environment and _env_file; mypy only sees
    # the field-based __init__ that pydantic's dataclass transform declares.
    return CoreSettings(_env_file=repo_env_file())  # type: ignore[call-arg]
