from pathlib import Path

import pytest
from typer.testing import CliRunner

from hirevion_devcli.cli import app

runner = CliRunner()


def make_repo(root: Path) -> None:
    (root / "MASTER_IMPLEMENTATION_PLAN.md").write_text("# plan\n", encoding="utf-8")
    (root / ".env.example").write_text("POSTGRES_PASSWORD=\nOPENAI_API_KEY=\n", encoding="utf-8")


def test_init_env_creates_env_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    first = runner.invoke(app, ["init-env"])
    assert first.exit_code == 0
    assert "Created .env" in first.output
    assert (tmp_path / ".env").exists()
    second = runner.invoke(app, ["init-env"])
    assert "already exists" in second.output


def test_env_sync_adds_new_keys_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_repo(tmp_path)
    (tmp_path / ".env.example").write_text("A=\nGEMINI_API_KEY=\n", encoding="utf-8")
    (tmp_path / ".env").write_text("A=mine\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    first = runner.invoke(app, ["env-sync"])
    assert first.exit_code == 0
    assert "GEMINI_API_KEY" in first.output
    assert (tmp_path / ".env").read_text(encoding="utf-8").startswith("A=mine\n")
    second = runner.invoke(app, ["env-sync"])
    assert "up to date" in second.output


def test_env_sync_requires_existing_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["env-sync"]).exit_code == 1


def test_doctor_exits_nonzero_when_env_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert ".env" in result.output
