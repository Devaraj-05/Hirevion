import subprocess
from collections.abc import Sequence
from pathlib import Path

import httpx
import respx

from hirevion_devcli.doctor import gather, summarize_models
from hirevion_devcli.vendors import DEEPGRAM_PROJECTS_URL, OPENAI_MODELS_URL

OPENAI_KEY = "openai-test-" + "x" * 40
DEEPGRAM_KEY = "deepgram-test-" + "y" * 40


def runner(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    if list(args[1:2]) == ["info"]:
        return subprocess.CompletedProcess(
            list(args), 0, stdout='{"MemTotal": 17179869184, "NCPU": 8}', stderr=""
        )
    return subprocess.CompletedProcess(list(args), 0, stdout="v99.0.0", stderr="")


def test_gather_without_env_skips_vendor_checks(tmp_path: Path) -> None:
    results, models = gather(tmp_path, which=lambda name: name, runner=runner)
    names = [r.name for r in results]
    assert names == ["git", "docker", "uv", "node", "pnpm", "cargo", ".env"]
    assert models == []


@respx.mock
def test_gather_with_keys_checks_vendors(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        f"OPENAI_API_KEY={OPENAI_KEY}\nDEEPGRAM_API_KEY={DEEPGRAM_KEY}\n", encoding="utf-8"
    )
    respx.get(OPENAI_MODELS_URL).mock(
        return_value=httpx.Response(200, json={"data": [{"id": "gpt-test"}]})
    )
    respx.get(DEEPGRAM_PROJECTS_URL).mock(return_value=httpx.Response(200, json={"projects": []}))
    with httpx.Client() as client:
        results, models = gather(tmp_path, which=lambda name: name, runner=runner, client=client)
    by_name = {r.name: r for r in results}
    assert by_name["openai"].status == "ok"
    assert by_name["deepgram"].status == "ok"
    assert models == ["gpt-test"]
    assert all(OPENAI_KEY not in r.detail and DEEPGRAM_KEY not in r.detail for r in results)


def test_summarize_models_keeps_relevant_families() -> None:
    models = [
        "dall-e-3",
        "gpt-4o-mini-tts",
        "gpt-5",
        "gpt-5-mini",
        "omni-moderation-latest",
        "text-embedding-3-large",
        "whisper-1",
    ]
    assert summarize_models(models) == [
        "gpt-4o-mini-tts",
        "gpt-5",
        "gpt-5-mini",
        "text-embedding-3-large",
        "whisper-1",
    ]
