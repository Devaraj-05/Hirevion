import json
import subprocess
from collections.abc import Callable, Sequence

from hirevion_devcli.checks import (
    CheckResult,
    check_docker,
    check_env,
    check_tool,
    parse_version,
)


def fake_runner(
    stdout: str, returncode: int = 0
) -> Callable[[Sequence[str]], subprocess.CompletedProcess[str]]:
    def run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(list(args), returncode, stdout=stdout, stderr="")

    return run


def test_parse_version_handles_common_formats() -> None:
    assert parse_version("v24.15.0") == (24, 15, 0)
    assert parse_version("git version 2.47.1.windows.1") == (2, 47, 1)
    assert parse_version("uv 0.12.19 (bea1384 2026-09-24)") == (0, 12, 19)
    assert parse_version("cargo 1.90") == (1, 90, 0)
    assert parse_version("no digits") is None


def test_missing_required_tool_fails_and_optional_warns() -> None:
    def no_tools(_: str) -> None:
        return None

    assert check_tool("node", ["--version"], (24, 0, 0), which=no_tools).status == "fail"
    optional = check_tool("cargo", ["--version"], (1, 85, 0), required=False, which=no_tools)
    assert optional.status == "warn"


def test_old_tool_version_fails() -> None:
    result = check_tool(
        "node",
        ["--version"],
        (24, 0, 0),
        which=lambda _: "node",
        runner=fake_runner("v22.1.0"),
    )
    assert result == CheckResult("node", "fail", "22.1.0 found; 24.0.0+ needed")


def test_current_tool_version_passes() -> None:
    result = check_tool(
        "node", ["--version"], (24, 0, 0), which=lambda _: "node", runner=fake_runner("v24.15.0")
    )
    assert result == CheckResult("node", "ok", "24.15.0")


def test_docker_not_running_fails() -> None:
    result = check_docker(which=lambda _: "docker", runner=fake_runner("", returncode=1))
    assert result.status == "fail"


def test_docker_with_small_vm_warns() -> None:
    info = json.dumps({"MemTotal": 4 * 1024**3, "NCPU": 2})
    result = check_docker(which=lambda _: "docker", runner=fake_runner(info))
    assert result.status == "warn"


def test_docker_with_enough_resources_passes() -> None:
    info = json.dumps({"MemTotal": 16 * 1024**3, "NCPU": 8})
    result = check_docker(which=lambda _: "docker", runner=fake_runner(info))
    assert result == CheckResult("docker", "ok", "16.0 GB RAM, 8 CPUs available to Docker")


def test_env_check() -> None:
    assert check_env(None).status == "fail"
    assert check_env({"GEMINI_API_KEY": "", "DEEPGRAM_API_KEY": ""}).status == "fail"
    values = {"GEMINI_API_KEY": "a" * 40, "DEEPGRAM_API_KEY": "b" * 40}
    assert check_env(values) == CheckResult(".env", "ok", "API keys present")
