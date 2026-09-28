from pathlib import Path

import pytest
from typer.testing import CliRunner

from hirevion_devcli import cli
from hirevion_devcli.checks import CheckResult
from hirevion_devcli.stack import ALL_PROFILES, compose_command
from hirevion_devcli.trust import LOCAL_CA_PATH, export_ca_command, trust_ca_command

runner = CliRunner()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "MASTER_IMPLEMENTATION_PLAN.md").write_text("# plan\n", encoding="utf-8")
    (tmp_path / ".env").write_text("POSTGRES_USER=hirevion\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return Path.cwd().resolve()


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    recorded: list[list[str]] = []

    def fake_run(command: list[str]) -> int:
        recorded.append(command)
        return 0

    monkeypatch.setattr(cli, "_run_stream", fake_run)
    return recorded


def test_up_starts_default_profiles_and_waits(repo: Path, calls: list[list[str]]) -> None:
    result = runner.invoke(cli.app, ["up"])
    assert result.exit_code == 0
    assert calls == [
        compose_command(
            repo,
            ["core", "edge", "media"],
            "up",
            "--detach",
            "--wait",
            "--wait-timeout",
            "600",
            "--remove-orphans",
        )
    ]


def test_up_with_obs_adds_the_obs_profile(repo: Path, calls: list[list[str]]) -> None:
    assert runner.invoke(cli.app, ["up", "--obs"]).exit_code == 0
    assert "obs" in calls[0]


def test_up_requires_env(repo: Path, calls: list[list[str]]) -> None:
    (repo / ".env").unlink()
    assert runner.invoke(cli.app, ["up"]).exit_code == 1
    assert calls == []


def test_down_stops_every_profile(repo: Path, calls: list[list[str]]) -> None:
    assert runner.invoke(cli.app, ["down"]).exit_code == 0
    assert calls == [compose_command(repo, ALL_PROFILES, "down")]


def test_reset_needs_confirmation(repo: Path, calls: list[list[str]]) -> None:
    assert runner.invoke(cli.app, ["reset"], input="n\n").exit_code == 1
    assert calls == []
    assert runner.invoke(cli.app, ["reset", "--yes"]).exit_code == 0
    assert calls == [compose_command(repo, ALL_PROFILES, "down", "--volumes")]


def test_trust_ca_exports_then_trusts(repo: Path, calls: list[list[str]]) -> None:
    assert runner.invoke(cli.app, ["trust-ca"]).exit_code == 0
    assert calls == [export_ca_command(repo), trust_ca_command(repo / LOCAL_CA_PATH)]


def test_smoke_exit_code_follows_results(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def ok(*args: object, **kwargs: object) -> list[CheckResult]:
        return [CheckResult("postgres", "ok", "fine")]

    def failing(*args: object, **kwargs: object) -> list[CheckResult]:
        return [CheckResult("postgres", "fail", "down")]

    monkeypatch.setattr(cli, "run_smoke", ok)
    assert runner.invoke(cli.app, ["smoke"]).exit_code == 0
    monkeypatch.setattr(cli, "run_smoke", failing)
    assert runner.invoke(cli.app, ["smoke"]).exit_code == 1


def test_hosts_reports_names_that_still_fail(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "ensure_hosts", lambda *args, **kwargs: ["api.hirevion.localhost"])
    result = runner.invoke(cli.app, ["hosts"])
    assert result.exit_code == 1
    assert "api.hirevion.localhost" in result.output
    monkeypatch.setattr(cli, "ensure_hosts", lambda *args, **kwargs: [])
    assert runner.invoke(cli.app, ["hosts"]).exit_code == 0
