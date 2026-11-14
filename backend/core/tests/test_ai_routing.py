"""Which provider serves which AI task (owner decision, ADR-0034): OpenRouter reads job
descriptions and resumes and screens them; NVIDIA Nemotron asks the interview questions and
evaluates the answers."""

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

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
        ("jd.embed", SCREENING),
        ("job.embed", SCREENING),
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


def _purpose_argument(call: ast.Call) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg == "purpose":
            return keyword.value
    return call.args[1] if len(call.args) > 1 else None


def _called_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    return call.func.attr if isinstance(call.func, ast.Attribute) else None


def _purposes_in(tree: ast.Module, where: str) -> tuple[set[str], list[str]]:
    """Each `AiContext(...)`'s purpose: a literal, a module constant, or the literal that the
    enclosing function's callers pass for that parameter. Anything else is unresolved."""
    constants = {
        target.id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    found: set[str] = set()
    unresolved: list[str] = []
    functions = [
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    for function in functions:
        parameters = [argument.arg for argument in function.args.args]
        for call in ast.walk(function):
            if not (isinstance(call, ast.Call) and _called_name(call) == "AiContext"):
                continue
            purpose = _purpose_argument(call)
            if isinstance(purpose, ast.Constant) and isinstance(purpose.value, str):
                found.add(purpose.value)
            elif isinstance(purpose, ast.Name) and purpose.id in constants:
                found.add(constants[purpose.id])
            elif isinstance(purpose, ast.Name) and purpose.id in parameters:
                index = parameters.index(purpose.id)
                for caller in calls:
                    if _called_name(caller) != function.name:
                        continue
                    passed = next(
                        (k.value for k in caller.keywords if k.arg == purpose.id),
                        caller.args[index] if index < len(caller.args) else None,
                    )
                    if isinstance(passed, ast.Constant) and isinstance(passed.value, str):
                        found.add(passed.value)
                    else:
                        unresolved.append(f"{where}:{caller.lineno}")
            else:
                unresolved.append(f"{where}:{call.lineno}")
    return found, unresolved


def test_every_task_in_the_code_has_a_route() -> None:
    """A new purpose must be given a provider before it ships."""
    found: set[str] = set()
    unresolved: list[str] = []
    for package in ("core", "api", "interview_agent"):
        for path in (REPO / "backend" / package / "src").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            purposes, unknown = _purposes_in(tree, path.name)
            found |= purposes
            unresolved += unknown
    assert not unresolved, f"purposes this test can't read: {unresolved}"
    # The scan reaches each way purposes are written: constants, aliases and call sites.
    assert {"resume.parse", "evaluation.synthesis", "resume.embed"} <= found
    for purpose in sorted(found):
        route_for(purpose)


@pytest.mark.parametrize(
    ("setting", "provider"),
    [
        # Nemotron serves no embeddings or page reading here.
        ("screening_provider", "nemotron"),
        # In `dev`, OpenAI would read Gemini's model names (HV_LLM_MODEL_*).
        ("screening_provider", "openai"),
        ("interview_provider", "openai"),
    ],
)
def test_a_route_refuses_a_provider_it_cannot_use(setting: str, provider: str) -> None:
    with pytest.raises(ValidationError, match=setting):
        AiSettings(**{setting: provider})
