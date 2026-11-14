"""Which provider serves which AI task (owner decision, ADR-0034): OpenRouter reads job
descriptions and resumes and screens them; NVIDIA Nemotron asks the interview questions and
evaluates the answers."""

import re
from pathlib import Path

import pytest

from hirevion_core.ai.routing import INTERVIEW, SCREENING, route_for
from hirevion_core.ai.settings import AiSettings

REPO = Path(__file__).resolve().parents[3]


def test_the_provider_keys_load_from_the_env_file_in_any_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("NEMOTRON_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    env = tmp_path / ".env"
    env.write_text("nemotron_API_KEY=n-key\nOpenRouter_API_KEY=o-key\n", encoding="utf-8")
    settings = AiSettings(_env_file=env)  # type: ignore[call-arg]
    assert settings.nemotron_api_key.get_secret_value() == "n-key"
    assert settings.openrouter_api_key.get_secret_value() == "o-key"
    assert (settings.screening_provider, settings.interview_provider) == ("openrouter", "nemotron")


@pytest.mark.parametrize(
    ("purpose", "route"),
    [
        ("jd.extract", SCREENING),
        ("resume.parse", SCREENING),
        ("resume.ocr", SCREENING),
        ("screening.assess", SCREENING),
        ("screening.rank", SCREENING),
        ("questions.generate", INTERVIEW),
        ("interview.analyze", INTERVIEW),
        ("interview.follow_up", INTERVIEW),
        ("evaluation.question", INTERVIEW),
        ("evaluation.synthesis", INTERVIEW),
        ("evaluation.coding", INTERVIEW),
    ],
)
def test_each_task_has_its_provider(purpose: str, route: str) -> None:
    assert route_for(purpose) == route


def test_a_task_without_a_route_is_refused_rather_than_guessed() -> None:
    with pytest.raises(ValueError, match="no AI route"):
        route_for("payroll.calculate")


def test_every_task_in_the_code_has_a_route() -> None:
    """A new purpose must be given a provider before it ships."""
    pattern = re.compile(r'AiContext\([^)]*?"([a-z_]+\.[a-z_.]+)"', re.DOTALL)
    found: set[str] = set()
    for package in ("core", "api", "interview_agent"):
        for path in (REPO / "backend" / package / "src").rglob("*.py"):
            found.update(pattern.findall(path.read_text(encoding="utf-8")))
    assert found, "no AI purposes found: the pattern no longer matches the code"
    for purpose in sorted(found):
        route_for(purpose)
