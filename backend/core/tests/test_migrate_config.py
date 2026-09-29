from pathlib import Path

import pytest

from hirevion_core.db.migrate import MIGRATIONS_DIR, alembic_config


def test_the_repository_migrations_are_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HV_MIGRATIONS_DIR", raising=False)
    config = alembic_config()
    assert config.config_file_name == str(MIGRATIONS_DIR / "alembic.ini")
    assert (MIGRATIONS_DIR / "versions" / "0001_baseline.py").exists()


def test_an_image_can_point_elsewhere(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "alembic.ini").write_text(
        "[alembic]\nscript_location = %(here)s\n", encoding="utf-8"
    )
    monkeypatch.setenv("HV_MIGRATIONS_DIR", str(tmp_path))
    assert alembic_config().config_file_name == str(tmp_path / "alembic.ini")


def test_a_missing_directory_is_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HV_MIGRATIONS_DIR", str(tmp_path / "nowhere"))
    with pytest.raises(FileNotFoundError, match="nowhere"):
        alembic_config()
