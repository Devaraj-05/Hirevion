from pathlib import Path

import pytest
from pydantic import ValidationError

from hirevion_core.settings import APP_ROLE, RELAY_ROLE, CoreSettings

ADMIN_PASSWORD = "admin-" + "a" * 26
APP_PASSWORD = "app-" + "b" * 28
RELAY_PASSWORD = "relay-" + "c" * 26
NAMES = (
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_USER",
    "POSTGRES_DB",
    "POSTGRES_PASSWORD",
    "POSTGRES_APP_PASSWORD",
    "POSTGRES_RELAY_PASSWORD",
    "VALKEY_HOST",
    "VALKEY_PORT",
    "VALKEY_PASSWORD",
)


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in NAMES:
        monkeypatch.delenv(name, raising=False)


def settings_from(tmp_path: Path, **values: str) -> CoreSettings:
    env = tmp_path / ".env"
    env.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
    return CoreSettings(_env_file=env)  # type: ignore[call-arg]


def complete(tmp_path: Path, **overrides: str) -> CoreSettings:
    values = {
        "POSTGRES_USER": "hirevion",
        "POSTGRES_DB": "hirevion",
        "POSTGRES_PASSWORD": ADMIN_PASSWORD,
        "POSTGRES_APP_PASSWORD": APP_PASSWORD,
        "POSTGRES_RELAY_PASSWORD": RELAY_PASSWORD,
        "VALKEY_PASSWORD": "valkey-" + "v" * 25,
    }
    values.update(overrides)
    return settings_from(tmp_path, **values)


def test_database_urls_for_each_role(tmp_path: Path) -> None:
    settings = complete(tmp_path)
    assert settings.database_url("admin") == (
        f"postgresql+asyncpg://hirevion:{ADMIN_PASSWORD}@127.0.0.1:5432/hirevion"
    )
    assert settings.database_url("app", "hirevion_test") == (
        f"postgresql+asyncpg://{APP_ROLE}:{APP_PASSWORD}@127.0.0.1:5432/hirevion_test"
    )
    assert settings.database_url("relay").startswith(f"postgresql+asyncpg://{RELAY_ROLE}:")


def test_passwords_are_url_encoded(tmp_path: Path) -> None:
    settings = complete(tmp_path, POSTGRES_PASSWORD="p@ss:w/rd#1")
    assert "p%40ss%3Aw%2Frd%231@" in settings.database_url("admin")


def test_valkey_url_with_and_without_a_password(tmp_path: Path) -> None:
    assert complete(tmp_path).valkey_url() == f"redis://:{'valkey-' + 'v' * 25}@127.0.0.1:6379/0"
    assert complete(tmp_path, VALKEY_PASSWORD="").valkey_url() == "redis://127.0.0.1:6379/0"


def test_missing_passwords_are_named_but_never_shown(tmp_path: Path) -> None:
    with pytest.raises(ValidationError) as error:
        settings_from(tmp_path, POSTGRES_USER="hirevion", POSTGRES_PASSWORD=ADMIN_PASSWORD)
    message = str(error.value)
    assert "postgres_app_password" in message
    assert ADMIN_PASSWORD not in message


def test_repr_contains_no_secret(tmp_path: Path) -> None:
    text = repr(complete(tmp_path))
    for secret in (ADMIN_PASSWORD, APP_PASSWORD, RELAY_PASSWORD):
        assert secret not in text
