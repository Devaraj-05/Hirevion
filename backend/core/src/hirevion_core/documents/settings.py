"""Document pipeline settings (`HV_CLAMAV_*`, `HV_DOCUMENTS_SCAN`). Locally ClamAV runs in the
`core` compose profile on 127.0.0.1:3310."""

from __future__ import annotations

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from hirevion_core.settings import repo_env_file


class DocumentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HV_", extra="ignore", hide_input_in_errors=True)

    clamav_host: str = "127.0.0.1"
    clamav_port: int = 3310
    # Scanning may be switched off only outside production (ClamAV's first start is slow).
    documents_scan: bool = True
    environment: str = "development"

    @model_validator(mode="after")
    def _scan_in_production(self) -> DocumentSettings:
        if self.environment == "production" and not self.documents_scan:
            raise ValueError("HV_DOCUMENTS_SCAN cannot be false in production")
        return self


def load_document_settings() -> DocumentSettings:
    return DocumentSettings(_env_file=repo_env_file())  # type: ignore[call-arg]
