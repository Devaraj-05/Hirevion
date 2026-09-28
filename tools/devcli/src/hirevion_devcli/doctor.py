"""Runs every environment check for `hv doctor`."""

from __future__ import annotations

from pathlib import Path

import httpx

from .checks import (
    CheckResult,
    Runner,
    Which,
    check_docker,
    check_env,
    check_tool,
    find_tool,
    run_command,
)
from .envfile import missing_required, parse_env
from .vendors import check_deepgram, check_openai

_MODEL_PREFIXES = ("gpt-", "o1", "o3", "o4", "text-embedding-", "tts-", "whisper-")


def summarize_models(models: list[str]) -> list[str]:
    """Keep the model families Hirevion can use (LLM, embeddings, speech)."""
    return sorted(model for model in models if model.startswith(_MODEL_PREFIXES))


def gather(
    repo_root: Path,
    *,
    which: Which = find_tool,
    runner: Runner = run_command,
    client: httpx.Client | None = None,
) -> tuple[list[CheckResult], list[str]]:
    results = [
        check_tool("git", ["--version"], (2, 40, 0), which=which, runner=runner),
        check_docker(which=which, runner=runner),
        check_tool("uv", ["--version"], (0, 5, 0), which=which, runner=runner),
        check_tool("node", ["--version"], (24, 0, 0), which=which, runner=runner),
        check_tool("pnpm", ["--version"], (9, 0, 0), which=which, runner=runner),
        check_tool("cargo", ["--version"], (1, 85, 0), required=False, which=which, runner=runner),
    ]
    env_path = repo_root / ".env"
    values = parse_env(env_path.read_text(encoding="utf-8")) if env_path.exists() else None
    results.append(check_env(values))
    models: list[str] = []
    if values is not None and not missing_required(values):
        http = client if client is not None else httpx.Client(timeout=20)
        try:
            openai_result, models = check_openai(values["OPENAI_API_KEY"], http)
            results.append(openai_result)
            results.append(check_deepgram(values["DEEPGRAM_API_KEY"], http))
        finally:
            if client is None:
                http.close()
    return results, models
