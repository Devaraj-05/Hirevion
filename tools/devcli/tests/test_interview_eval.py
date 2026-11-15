"""`hv eval-interviews`: the gate in CI, and a regressed prompt blocked (SP-10 Task 7)."""

from pathlib import Path

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from hirevion_core.ai.settings import AiSettings
from hirevion_devcli import interview_eval
from hirevion_devcli.cli import app

runner = CliRunner()
BAD_PROMPT = (
    Path(__file__).resolve().parents[3]
    / "backend"
    / "core"
    / "tests"
    / "evaluation"
    / "fixtures"
    / "bad-prompt.md"
)


def test_the_active_prompt_passes_on_the_mock_profile_with_no_keys_or_database() -> None:
    result = runner.invoke(app, ["eval-interviews"])
    assert result.exit_code == 0, result.output
    assert "Gate passed" in result.output and "evaluation-question-v2" in result.output


def test_a_regressed_prompt_fails_the_gate_with_exit_code_one(tmp_path: Path) -> None:
    report = tmp_path / "gate.md"
    result = runner.invoke(
        app, ["eval-interviews", "--prompt-file", str(BAD_PROMPT), "--report", str(report)]
    )
    assert result.exit_code == 1, result.output
    assert "BLOCKED" in result.output and "bad-prompt" in result.output
    text = report.read_text(encoding="utf-8")
    assert "**blocked**" in text and "evidence_rate" in text


def test_an_unknown_prompt_version_is_refused() -> None:
    result = runner.invoke(app, ["eval-interviews", "--prompt-version", "evaluation-question-v9"])
    assert result.exit_code == 1 and "no prompt named" in result.output


def test_live_needs_a_real_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HV_AI_PROFILE", "mock")
    result = runner.invoke(app, ["eval-interviews", "--live"])
    assert result.exit_code == 1 and "HV_AI_PROFILE is mock" in result.output


def test_the_baseline_is_only_rewritten_by_a_passing_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "baseline.json"
    monkeypatch.setattr(interview_eval, "baseline_path", lambda: target)
    blocked = runner.invoke(
        app, ["eval-interviews", "--prompt-file", str(BAD_PROMPT), "--update-baseline"]
    )
    assert blocked.exit_code == 1 and not target.exists()
    passing = runner.invoke(app, ["eval-interviews", "--update-baseline"])
    assert passing.exit_code == 0 and target.exists()
    committed = Path(str(interview_eval.files("hirevion_core.evaluation"))) / "eval_set"
    assert target.read_text(encoding="utf-8") == (committed / "baseline.json").read_text(
        encoding="utf-8"
    )


def test_a_rerun_needs_an_interview_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "MASTER_IMPLEMENTATION_PLAN.md").write_text("# plan\n", encoding="utf-8")
    (tmp_path / ".env").write_text("POSTGRES_PASSWORD=x\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["eval-rerun", "not-an-id"])
    assert result.exit_code == 1 and "UUID" in result.output


class _Built(Exception):
    """Stops the gate once the backend is chosen."""


@pytest.mark.parametrize("provider", ["nemotron", "openrouter"])
async def test_live_scores_the_model_the_interview_route_uses(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    """The gate must certify the model that really evaluates interviews (ADR-0034)."""
    settings = AiSettings(
        profile="dev",
        interview_provider=provider,  # type: ignore[arg-type]
        openrouter_api_key=SecretStr("o-key"),
        nemotron_api_key=SecretStr("n-key"),
    )
    chosen: list[str] = []

    def build(_settings: AiSettings, _recorder: object, name: str) -> None:
        chosen.append(name)
        raise _Built

    monkeypatch.setattr(interview_eval, "load_ai_settings", lambda: settings)
    monkeypatch.setattr(interview_eval, "OpenAICompatible", build)
    with pytest.raises(_Built):
        await interview_eval.run_gate(live=True)
    assert chosen == [provider]
