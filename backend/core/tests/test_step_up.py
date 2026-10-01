"""The step-up window: how long a confirmed password unlocks sensitive changes (ADR-0014)."""

from datetime import UTC, datetime, timedelta

from hirevion_core.identity.sessions import SessionContext, is_stepped_up
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.ids import uuid7

NOW = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)


def context(stepped_up_at: datetime | None) -> SessionContext:
    return SessionContext(uuid7(), uuid7(), uuid7(), b"csrf-hash", stepped_up_at)


def test_a_session_that_never_confirmed_is_not_stepped_up() -> None:
    assert not is_stepped_up(context(None), IdentitySettings(), NOW)


def test_a_confirmation_lasts_ten_minutes_by_default() -> None:
    settings = IdentitySettings()
    assert is_stepped_up(context(NOW - timedelta(minutes=9)), settings, NOW)
    assert not is_stepped_up(context(NOW - timedelta(minutes=11)), settings, NOW)


def test_the_window_is_configurable() -> None:
    settings = IdentitySettings(step_up_minutes=2)
    assert settings.step_up_window == timedelta(minutes=2)
    assert not is_stepped_up(context(NOW - timedelta(minutes=3)), settings, NOW)
