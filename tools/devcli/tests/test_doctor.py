import subprocess
from collections.abc import Sequence
from pathlib import Path

import httpx
import respx

from hirevion_devcli.doctor import gather, summarize_models
from hirevion_devcli.vendors import DEEPGRAM_PROJECTS_URL, GEMINI_MODELS_URL, OPENAI_MODELS_URL

GEMINI_KEY = "gemini-test-" + "g" * 40
OPENAI_KEY = "openai-test-" + "x" * 40
DEEPGRAM_KEY = "deepgram-test-" + "y" * 40


def runner(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    if list(args[1:2]) == ["info"]:
        return subprocess.CompletedProcess(
            list(args), 0, stdout='{"MemTotal": 17179869184, "NCPU": 8}', stderr=""
        )
    return subprocess.CompletedProcess(list(args), 0, stdout="v99.0.0", stderr="")


def write_env(root: Path, **keys: str) -> None:
    (root / ".env").write_text(
        "".join(f"{name}={value}\n" for name, value in keys.items()), encoding="utf-8"
    )


def test_gather_without_env_skips_vendor_checks(tmp_path: Path) -> None:
    results, models = gather(tmp_path, which=lambda name: name, runner=runner)
    names = [r.name for r in results]
    assert names == ["git", "docker", "uv", "node", "pnpm", "cargo", ".env"]
    assert models == {}


@respx.mock
def test_gather_checks_gemini_and_deepgram(tmp_path: Path) -> None:
    write_env(tmp_path, GEMINI_API_KEY=GEMINI_KEY, DEEPGRAM_API_KEY=DEEPGRAM_KEY)
    respx.get(GEMINI_MODELS_URL).mock(
        return_value=httpx.Response(200, json={"models": [{"name": "models/gemini-test"}]})
    )
    respx.get(DEEPGRAM_PROJECTS_URL).mock(return_value=httpx.Response(200, json={"projects": []}))
    with httpx.Client() as client:
        results, models = gather(tmp_path, which=lambda name: name, runner=runner, client=client)
    by_name = {r.name: r for r in results}
    assert by_name[".env"].status == "ok"
    assert by_name["gemini"].status == "ok"
    assert by_name["deepgram"].status == "ok"
    assert "openai" not in by_name
    assert models == {"gemini": ["gemini-test"]}
    keys = (GEMINI_KEY, DEEPGRAM_KEY)
    assert all(key not in r.detail for r in results for key in keys)


@respx.mock
def test_gather_checks_openai_when_its_key_is_set(tmp_path: Path) -> None:
    write_env(
        tmp_path,
        GEMINI_API_KEY=GEMINI_KEY,
        DEEPGRAM_API_KEY=DEEPGRAM_KEY,
        OPENAI_API_KEY=OPENAI_KEY,
    )
    respx.get(GEMINI_MODELS_URL).mock(return_value=httpx.Response(200, json={"models": []}))
    respx.get(DEEPGRAM_PROJECTS_URL).mock(return_value=httpx.Response(200, json={"projects": []}))
    respx.get(OPENAI_MODELS_URL).mock(
        return_value=httpx.Response(200, json={"data": [{"id": "gpt-test"}]})
    )
    with httpx.Client() as client:
        results, models = gather(tmp_path, which=lambda name: name, runner=runner, client=client)
    assert {r.name: r.status for r in results}["openai"] == "ok"
    assert models["openai"] == ["gpt-test"]


@respx.mock
def test_gather_checks_each_vendor_independently(tmp_path: Path) -> None:
    write_env(tmp_path, DEEPGRAM_API_KEY=DEEPGRAM_KEY)
    respx.get(DEEPGRAM_PROJECTS_URL).mock(return_value=httpx.Response(200, json={"projects": []}))
    with httpx.Client() as client:
        results, _ = gather(tmp_path, which=lambda name: name, runner=runner, client=client)
    by_name = {r.name: r for r in results}
    assert by_name[".env"].status == "fail"
    assert by_name["deepgram"].status == "ok"
    assert "gemini" not in by_name


def test_summarize_models_keeps_relevant_families() -> None:
    models = [
        "dall-e-3",
        "gemini-2.5-flash",
        "gemini-embedding-001",
        "gpt-4o-mini-tts",
        "gpt-5",
        "imagen-4.0-generate-001",
        "omni-moderation-latest",
        "text-embedding-3-large",
        "whisper-1",
    ]
    assert summarize_models(models) == [
        "gemini-2.5-flash",
        "gemini-embedding-001",
        "gpt-4o-mini-tts",
        "gpt-5",
        "text-embedding-3-large",
        "whisper-1",
    ]
