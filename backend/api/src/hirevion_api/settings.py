"""API process settings (`HV_API_*`), read from the environment and the repository's `.env`."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

from hirevion_core.settings import repo_env_file


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HV_API_", extra="ignore")

    # Host names the API answers to (without port); anything else gets 400 host-not-allowed.
    # `host.docker.internal` is how LiveKit's container delivers its webhooks locally.
    allowed_hosts: str = (
        "api.hirevion.localhost,app.hirevion.localhost,candidate.hirevion.localhost,localhost,"
        "127.0.0.1,host.docker.internal"
    )
    # Proxies whose X-Forwarded-For is believed (Caddy reaches `hv api` from loopback).
    trusted_proxies: str = "127.0.0.1"
    max_body_bytes: int = 1_048_576
    # File uploads (a job description, resumes): 10 MiB files plus the multipart framing.
    max_upload_bytes: int = 11 * 1_048_576
    # Resumes: a ZIP of up to 50 MiB plus the framing.
    max_archive_upload_bytes: int = 51 * 1_048_576
    # Requests per window per client IP, across the whole API.
    ip_rate_limit: int = 600
    ip_rate_window_seconds: int = 60
    docs_enabled: bool = True
    # Origins whose cookie-authenticated requests are accepted (CSRF), comma-separated: the
    # app through Caddy, `next dev`, and the end-to-end server.
    allowed_origins: str = (
        "https://app.hirevion.localhost,http://localhost:3000,http://127.0.0.1:3000,"
        "http://app.hirevion.localhost:3100"
    )
    # The candidate portal's origins (ADR-0022): only they may use the candidate's cookies, and
    # they may never use the recruiter's. Caddy, `next dev` and the end-to-end server.
    portal_origins: str = (
        "https://candidate.hirevion.localhost,http://candidate.hirevion.localhost:3000,"
        "http://candidate.hirevion.localhost:3100"
    )
    # Run the outbox relay and the mail consumer in this process (else `hv worker` runs them).
    run_workers: bool = True

    @property
    def hosts(self) -> frozenset[str]:
        return frozenset(_split(self.allowed_hosts))

    @property
    def proxies(self) -> list[str]:
        return _split(self.trusted_proxies)

    @property
    def origins(self) -> frozenset[str]:
        # Origins keep their case-insensitive scheme and host, and drop a trailing slash.
        return frozenset(origin.rstrip("/") for origin in _split(self.allowed_origins))

    @property
    def portal(self) -> frozenset[str]:
        return frozenset(origin.rstrip("/") for origin in _split(self.portal_origins))


def _split(value: str) -> list[str]:
    return [item.strip().lower() for item in value.split(",") if item.strip()]


def load_api_settings() -> ApiSettings:
    return ApiSettings(_env_file=repo_env_file())  # type: ignore[call-arg]
