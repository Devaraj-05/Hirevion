# SP-00a Repository Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the monorepo a working Python toolchain, a developer CLI (`hv init-env`, `hv doctor`), secret-safe git hooks with a self-test, CI, and the first ADRs, so every later sub-project starts from a checked, reproducible base.

**Architecture:** A uv workspace at the repo root (virtual root project, Python 3.12) with one member, `tools/devcli` (package `hirevion-devcli`, console script `hv`). The CLI reads the gitignored root `.env`, checks local tools and Docker, and validates the OpenAI and Deepgram keys without ever printing them. Git hooks in `.githooks/` gain a secret guard, and `tools/hooks/test-hooks.sh` tests every hook in a throwaway repository. GitHub Actions runs the hook tests, lint, type-check, unit tests and gitleaks.

**Tech Stack:** uv 0.12, Python 3.12, Typer, Rich, httpx, pytest, respx, ruff, mypy, POSIX sh, GitHub Actions.

## Global Constraints

- Everything in `MASTER_IMPLEMENTATION_PLAN.md` §13 applies.
- Python `>=3.12,<3.13`; dependencies declared with lower bounds, exact versions pinned by `uv.lock` (committed).
- Commits: author and committer `Devaraj-05 <padma.devaraj1800@gmail.com>`; Conventional Commits; no Claude/Anthropic attribution of any kind.
- API keys live only in the gitignored root `.env`. No code, test, log line or error message may print a key value.
- Test files must not contain literal key-shaped strings (the pre-commit guard would block them); build such strings at runtime.

## File Structure

| Path | Responsibility |
|---|---|
| `.gitignore`, `.editorconfig`, `.python-version` | Repo hygiene; Python version for uv |
| `.env.example` | Template for the gitignored `.env` |
| `pyproject.toml` | uv workspace root, shared ruff/pytest/mypy config |
| `tools/devcli/pyproject.toml` | `hirevion-devcli` package and the `hv` script |
| `tools/devcli/src/hirevion_devcli/__init__.py` | Package version |
| `tools/devcli/src/hirevion_devcli/envfile.py` | Parse `.env`, detect missing keys, create `.env` with generated local secrets |
| `tools/devcli/src/hirevion_devcli/checks.py` | `CheckResult`, version parsing, tool / Docker / `.env` checks |
| `tools/devcli/src/hirevion_devcli/vendors.py` | OpenAI and Deepgram key checks over HTTPS |
| `tools/devcli/src/hirevion_devcli/doctor.py` | Runs all checks; summarises useful OpenAI models |
| `tools/devcli/src/hirevion_devcli/cli.py` | Typer app: `init-env`, `doctor` |
| `tools/devcli/tests/*.py` | Unit tests for each module |
| `.githooks/pre-commit` | Adds the `.env`/API-key guard |
| `tools/hooks/test-hooks.sh` | Self-test for all three hooks |
| `.github/workflows/ci.yml` | CI: hooks, python, secrets |
| `docs/architecture/adr/*.md` | ADR index, template, ADR-0001, ADR-0002 |
| `README.md` | What the repo is and first-time setup |

---

### Task 1: uv workspace and repo hygiene

**Files:**
- Create: `.gitignore`, `.editorconfig`, `.python-version`, `pyproject.toml`, `tools/devcli/pyproject.toml`, `tools/devcli/src/hirevion_devcli/__init__.py`
- Test: `tools/devcli/tests/test_package.py`

**Interfaces:**
- Produces: installable package `hirevion_devcli` with `__version__: str`; `uv run pytest` and `uv run ruff check .` work from the repo root.

- [ ] **Step 1: Write the failing test**

`tools/devcli/tests/test_package.py`:
```python
import re

import hirevion_devcli


def test_version_is_semver() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", hirevion_devcli.__version__)
```

- [ ] **Step 2: Create the workspace files**

`.python-version`:
```
3.12
```

`pyproject.toml`:
```toml
[project]
name = "hirevion"
version = "0.0.0"
description = "Hirevion monorepo workspace root"
requires-python = ">=3.12,<3.13"
dependencies = ["hirevion-devcli"]

[tool.uv]
package = false

[tool.uv.workspace]
members = ["tools/devcli"]

[tool.uv.sources]
hirevion-devcli = { workspace = true }

[dependency-groups]
dev = [
  "mypy>=1.11",
  "pytest>=8.3",
  "respx>=0.21",
  "ruff>=0.6",
]

[tool.ruff]
line-length = 100
target-version = "py312"
extend-exclude = ["docs"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "S", "RUF"]

[tool.ruff.lint.per-file-ignores]
"**/tests/**" = ["S101", "S106"]

[tool.pytest.ini_options]
testpaths = ["tools/devcli/tests"]
addopts = "-q --strict-markers"

[tool.mypy]
python_version = "3.12"
strict = true
```

`tools/devcli/pyproject.toml`:
```toml
[project]
name = "hirevion-devcli"
version = "0.1.0"
description = "Developer CLI for the Hirevion monorepo: environment setup, doctor and the local stack."
requires-python = ">=3.12,<3.13"
dependencies = [
  "httpx>=0.27",
  "rich>=13.7",
  "typer>=0.12",
]

[project.scripts]
hv = "hirevion_devcli.cli:app"

[build-system]
requires = ["hatchling>=1.25"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/hirevion_devcli"]
```

`tools/devcli/src/hirevion_devcli/__init__.py`:
```python
"""Developer CLI for the Hirevion monorepo."""

__version__ = "0.1.0"
```

`.gitignore`:
```
# Secrets: never commit. Create .env with `uv run hv init-env`.
.env
.env.*
!.env.example

# Python
__pycache__/
*.py[cod]
.venv/
.pytest_cache/
.mypy_cache/
.ruff_cache/
*.egg-info/
.coverage
htmlcov/

# Node
node_modules/
.next/
.turbo/
*.tsbuildinfo
coverage/

# Rust / Tauri
target/

# OS and editors
.DS_Store
Thumbs.db
.idea/

# Local runtime data
infrastructure/local/data/
*.log

# Claude Code personal settings
.claude/settings.local.json
```

`.editorconfig`:
```
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space
indent_size = 2

[*.py]
indent_size = 4

[*.md]
trim_trailing_whitespace = false

[*.{ps1,cmd,bat}]
end_of_line = crlf
```

- [ ] **Step 3: Sync and run the test**

Run: `uv sync` then `uv run pytest`
Expected: `1 passed`.

- [ ] **Step 4: Lint**

Run: `uv run ruff check .` and `uv run ruff format --check .`
Expected: no findings.

- [ ] **Step 5: Commit**

```bash
git add .gitignore .editorconfig .python-version pyproject.toml uv.lock tools/devcli
git commit -m "chore: set up uv workspace and developer CLI package"
```

---

### Task 2: `.env` handling and `hv init-env`

**Files:**
- Create: `.env.example`, `tools/devcli/src/hirevion_devcli/envfile.py`
- Test: `tools/devcli/tests/test_envfile.py`

**Interfaces:**
- Produces (in `hirevion_devcli.envfile`):
  - `REQUIRED_KEYS: tuple[str, ...]` = `("OPENAI_API_KEY", "DEEPGRAM_API_KEY")`
  - `GENERATED_KEYS: dict[str, int]` (key → secret length)
  - `parse_env(text: str) -> dict[str, str]`
  - `is_placeholder(value: str) -> bool`
  - `missing_required(values: dict[str, str], required: tuple[str, ...] = REQUIRED_KEYS) -> list[str]`
  - `generate_local_secrets() -> dict[str, str]`
  - `render_env(example_text: str, generated: dict[str, str]) -> str`
  - `init_env(example_path: Path, env_path: Path) -> bool`

- [ ] **Step 1: Write the failing tests**

`tools/devcli/tests/test_envfile.py`:
```python
from pathlib import Path

from hirevion_devcli.envfile import (
    GENERATED_KEYS,
    generate_local_secrets,
    init_env,
    is_placeholder,
    missing_required,
    parse_env,
    render_env,
)


def test_parse_env_skips_comments_and_strips_quotes() -> None:
    text = "# comment\n\nA=1\nexport B='two'\nC=\"three\"\nNOT_A_PAIR\nD=\n"
    assert parse_env(text) == {"A": "1", "B": "two", "C": "three", "D": ""}


def test_placeholders_are_detected() -> None:
    assert is_placeholder("")
    assert is_placeholder("  ")
    assert is_placeholder("changeme")
    assert is_placeholder("<your key>")
    assert is_placeholder("your-openai-key")
    assert not is_placeholder("real-value-" + "9" * 30)


def test_missing_required_lists_empty_and_placeholder_keys() -> None:
    values = {"OPENAI_API_KEY": "changeme", "DEEPGRAM_API_KEY": "k" * 40}
    assert missing_required(values) == ["OPENAI_API_KEY"]
    assert missing_required({}) == ["OPENAI_API_KEY", "DEEPGRAM_API_KEY"]


def test_generated_secrets_are_random_and_long_enough() -> None:
    first = generate_local_secrets()
    second = generate_local_secrets()
    assert set(first) == set(GENERATED_KEYS)
    for key, length in GENERATED_KEYS.items():
        assert len(first[key]) == length
        assert first[key] != second[key]


def test_render_env_fills_only_empty_generated_keys() -> None:
    example = "# c\nPOSTGRES_PASSWORD=\nLIVEKIT_API_SECRET=keep\nOPENAI_API_KEY=\n"
    rendered = render_env(example, {"POSTGRES_PASSWORD": "p" * 32, "LIVEKIT_API_SECRET": "s" * 48})
    assert parse_env(rendered) == {
        "POSTGRES_PASSWORD": "p" * 32,
        "LIVEKIT_API_SECRET": "keep",
        "OPENAI_API_KEY": "",
    }
    assert rendered.startswith("# c\n")


def test_init_env_creates_file_once(tmp_path: Path) -> None:
    example = tmp_path / ".env.example"
    example.write_text("POSTGRES_PASSWORD=\nOPENAI_API_KEY=\n", encoding="utf-8")
    env = tmp_path / ".env"
    assert init_env(example, env) is True
    created = env.read_text(encoding="utf-8")
    assert len(parse_env(created)["POSTGRES_PASSWORD"]) == GENERATED_KEYS["POSTGRES_PASSWORD"]
    assert init_env(example, env) is False
    assert env.read_text(encoding="utf-8") == created
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tools/devcli/tests/test_envfile.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'hirevion_devcli.envfile'`.

- [ ] **Step 3: Implement `envfile.py`**

`tools/devcli/src/hirevion_devcli/envfile.py`:
```python
"""Read and create the gitignored root .env file used for local development."""

from __future__ import annotations

import re
import secrets
from pathlib import Path

REQUIRED_KEYS: tuple[str, ...] = ("OPENAI_API_KEY", "DEEPGRAM_API_KEY")
GENERATED_KEYS: dict[str, int] = {
    "POSTGRES_PASSWORD": 32,
    "LIVEKIT_API_SECRET": 48,
    "GLITCHTIP_SECRET_KEY": 50,
}
_PLACEHOLDER = re.compile(r"^(<.*>|changeme|replace[-_ ]?me|your[-_ ].*)$", re.IGNORECASE)


def parse_env(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines, ignoring blanks and comments; strips quotes and 'export '."""
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def is_placeholder(value: str) -> bool:
    stripped = value.strip()
    return not stripped or _PLACEHOLDER.match(stripped) is not None


def missing_required(
    values: dict[str, str], required: tuple[str, ...] = REQUIRED_KEYS
) -> list[str]:
    return [key for key in required if is_placeholder(values.get(key, ""))]


def generate_local_secrets() -> dict[str, str]:
    return {key: secrets.token_urlsafe(length)[:length] for key, length in GENERATED_KEYS.items()}


def render_env(example_text: str, generated: dict[str, str]) -> str:
    """Return the example text with empty generated-secret keys filled in."""
    lines: list[str] = []
    for line in example_text.splitlines():
        name, sep, value = line.partition("=")
        name = name.strip()
        is_comment = line.lstrip().startswith("#")
        if sep and not is_comment and name in generated and not value.strip():
            lines.append(f"{name}={generated[name]}")
        else:
            lines.append(line)
    return "\n".join(lines) + "\n"


def init_env(example_path: Path, env_path: Path) -> bool:
    """Create env_path from example_path with fresh local secrets; never overwrites."""
    if env_path.exists():
        return False
    example_text = example_path.read_text(encoding="utf-8")
    env_path.write_text(render_env(example_text, generate_local_secrets()), encoding="utf-8")
    return True
```

`.env.example`:
```
# Local development settings.
# Run `uv run hv init-env` to create the gitignored .env with fresh local secrets,
# then paste your API keys into .env. Never commit .env.

# AI vendors (required)
OPENAI_API_KEY=
DEEPGRAM_API_KEY=

# Local infrastructure (secrets are generated by `hv init-env`)
POSTGRES_USER=hirevion
POSTGRES_DB=hirevion
POSTGRES_PASSWORD=
LIVEKIT_API_KEY=hirevion-local
LIVEKIT_API_SECRET=
GLITCHTIP_SECRET_KEY=

# This PC's LAN IP, so a phone on the same Wi-Fi can reach LiveKit (third-eye testing)
LIVEKIT_NODE_IP=127.0.0.1
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tools/devcli/tests/test_envfile.py`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add .env.example tools/devcli/src/hirevion_devcli/envfile.py tools/devcli/tests/test_envfile.py
git commit -m "feat(devcli): parse .env and generate local secrets"
```

---

### Task 3: Tool, Docker and `.env` checks

**Files:**
- Create: `tools/devcli/src/hirevion_devcli/checks.py`
- Test: `tools/devcli/tests/test_checks.py`

**Interfaces:**
- Consumes: `missing_required` from Task 2.
- Produces (in `hirevion_devcli.checks`):
  - `Status = Literal["ok", "warn", "fail"]`
  - `@dataclass(frozen=True) class CheckResult: name: str; status: Status; detail: str`
  - `Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]`
  - `Which = Callable[[str], str | None]`
  - `run_command(args: Sequence[str]) -> subprocess.CompletedProcess[str]`
  - `find_tool(name: str) -> str | None` (PATH, then `$UV` for uv)
  - `parse_version(text: str) -> tuple[int, int, int] | None`
  - `check_tool(name, version_args, minimum, *, required=True, which=find_tool, runner=run_command) -> CheckResult`
  - `check_docker(*, which=find_tool, runner=run_command) -> CheckResult`
  - `check_env(values: dict[str, str] | None) -> CheckResult`

- [ ] **Step 1: Write the failing tests**

`tools/devcli/tests/test_checks.py`:
```python
import json
import subprocess
from collections.abc import Sequence

from hirevion_devcli.checks import (
    CheckResult,
    check_docker,
    check_env,
    check_tool,
    parse_version,
)


def fake_runner(stdout: str, returncode: int = 0):
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
    assert check_env({"OPENAI_API_KEY": "", "DEEPGRAM_API_KEY": ""}).status == "fail"
    values = {"OPENAI_API_KEY": "a" * 40, "DEEPGRAM_API_KEY": "b" * 40}
    assert check_env(values) == CheckResult(".env", "ok", "API keys present")
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tools/devcli/tests/test_checks.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'hirevion_devcli.checks'`.

- [ ] **Step 3: Implement `checks.py`**

`tools/devcli/src/hirevion_devcli/checks.py`:
```python
"""Environment checks used by `hv doctor`."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from .envfile import missing_required

Status = Literal["ok", "warn", "fail"]
Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
Which = Callable[[str], str | None]

MIN_DOCKER_MEMORY_BYTES = 8 * 1024**3
MIN_DOCKER_CPUS = 4
_VERSION = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: Status
    detail: str


def run_command(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    # Fixed tool names and arguments only; never a shell, never user input.
    return subprocess.run(list(args), capture_output=True, text=True, timeout=60, check=False)  # noqa: S603


def find_tool(name: str) -> str | None:
    """Find a tool on PATH; `uv run` exposes its own binary as $UV."""
    found = shutil.which(name)
    if found is None and name == "uv":
        return os.environ.get("UV")
    return found


def parse_version(text: str) -> tuple[int, int, int] | None:
    match = _VERSION.search(text)
    if match is None:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch or 0)


def _dotted(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)


def check_tool(
    name: str,
    version_args: Sequence[str],
    minimum: tuple[int, int, int],
    *,
    required: bool = True,
    which: Which = find_tool,
    runner: Runner = run_command,
) -> CheckResult:
    missing: Status = "fail" if required else "warn"
    path = which(name)
    if path is None:
        return CheckResult(name, missing, "not found on PATH")
    completed = runner([path, *version_args])
    version = parse_version(completed.stdout + completed.stderr)
    if version is None:
        return CheckResult(name, "warn", "found, but its version could not be read")
    if version < minimum:
        return CheckResult(name, missing, f"{_dotted(version)} found; {_dotted(minimum)}+ needed")
    return CheckResult(name, "ok", _dotted(version))


def check_docker(*, which: Which = find_tool, runner: Runner = run_command) -> CheckResult:
    path = which("docker")
    if path is None:
        return CheckResult("docker", "fail", "Docker Desktop not found on PATH")
    completed = runner([path, "info", "--format", "{{json .}}"])
    if completed.returncode != 0:
        return CheckResult("docker", "fail", "Docker Desktop is not running")
    info = json.loads(completed.stdout)
    memory = int(info.get("MemTotal", 0))
    cpus = int(info.get("NCPU", 0))
    detail = f"{memory / 1024**3:.1f} GB RAM, {cpus} CPUs available to Docker"
    if memory < MIN_DOCKER_MEMORY_BYTES or cpus < MIN_DOCKER_CPUS:
        return CheckResult("docker", "warn", f"{detail} (8 GB and 4 CPUs recommended)")
    return CheckResult("docker", "ok", detail)


def check_env(values: dict[str, str] | None) -> CheckResult:
    if values is None:
        return CheckResult(".env", "fail", "missing; run `uv run hv init-env`")
    missing = missing_required(values)
    if missing:
        return CheckResult(".env", "fail", "add " + ", ".join(missing))
    return CheckResult(".env", "ok", "API keys present")
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tools/devcli/tests/test_checks.py`
Expected: `8 passed`.

- [ ] **Step 5: Commit**

```bash
git add tools/devcli/src/hirevion_devcli/checks.py tools/devcli/tests/test_checks.py
git commit -m "feat(devcli): add tool, Docker and .env checks"
```

---

### Task 4: OpenAI and Deepgram key checks

**Files:**
- Create: `tools/devcli/src/hirevion_devcli/vendors.py`
- Test: `tools/devcli/tests/test_vendors.py`

**Interfaces:**
- Consumes: `CheckResult` from Task 3.
- Produces (in `hirevion_devcli.vendors`):
  - `OPENAI_MODELS_URL`, `DEEPGRAM_PROJECTS_URL: str`
  - `check_openai(api_key: str, client: httpx.Client) -> tuple[CheckResult, list[str]]`
  - `check_deepgram(api_key: str, client: httpx.Client) -> CheckResult`

- [ ] **Step 1: Write the failing tests**

`tools/devcli/tests/test_vendors.py`:
```python
import httpx
import respx

from hirevion_devcli.vendors import (
    DEEPGRAM_PROJECTS_URL,
    OPENAI_MODELS_URL,
    check_deepgram,
    check_openai,
)

KEY = "test-" + "k" * 40


@respx.mock
def test_openai_valid_key_returns_models() -> None:
    route = respx.get(OPENAI_MODELS_URL).mock(
        return_value=httpx.Response(200, json={"data": [{"id": "model-b"}, {"id": "model-a"}]})
    )
    with httpx.Client() as client:
        result, models = check_openai(KEY, client)
    assert result.status == "ok"
    assert models == ["model-a", "model-b"]
    assert route.calls.last.request.headers["Authorization"] == f"Bearer {KEY}"


@respx.mock
def test_openai_rejected_key_fails_without_leaking_it() -> None:
    respx.get(OPENAI_MODELS_URL).mock(return_value=httpx.Response(401, json={"error": {}}))
    with httpx.Client() as client:
        result, models = check_openai(KEY, client)
    assert result.status == "fail"
    assert KEY not in result.detail
    assert models == []


@respx.mock
def test_openai_network_error_fails() -> None:
    respx.get(OPENAI_MODELS_URL).mock(side_effect=httpx.ConnectError("down"))
    with httpx.Client() as client:
        result, _ = check_openai(KEY, client)
    assert result.status == "fail"
    assert "network" in result.detail


@respx.mock
def test_deepgram_valid_key() -> None:
    route = respx.get(DEEPGRAM_PROJECTS_URL).mock(
        return_value=httpx.Response(200, json={"projects": [{"project_id": "p1"}]})
    )
    with httpx.Client() as client:
        result = check_deepgram(KEY, client)
    assert result.status == "ok"
    assert route.calls.last.request.headers["Authorization"] == f"Token {KEY}"


@respx.mock
def test_deepgram_rejected_key_fails() -> None:
    respx.get(DEEPGRAM_PROJECTS_URL).mock(return_value=httpx.Response(401))
    with httpx.Client() as client:
        result = check_deepgram(KEY, client)
    assert result.status == "fail"
    assert KEY not in result.detail


@respx.mock
def test_deepgram_key_without_project_scope_warns() -> None:
    respx.get(DEEPGRAM_PROJECTS_URL).mock(return_value=httpx.Response(403))
    with httpx.Client() as client:
        result = check_deepgram(KEY, client)
    assert result.status == "warn"
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tools/devcli/tests/test_vendors.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'hirevion_devcli.vendors'`.

- [ ] **Step 3: Implement `vendors.py`**

`tools/devcli/src/hirevion_devcli/vendors.py`:
```python
"""Live checks for the AI vendor keys. Never include a key in any result."""

from __future__ import annotations

import httpx

from .checks import CheckResult

OPENAI_MODELS_URL = "https://api.openai.com/v1/models"
DEEPGRAM_PROJECTS_URL = "https://api.deepgram.com/v1/projects"


def check_openai(api_key: str, client: httpx.Client) -> tuple[CheckResult, list[str]]:
    try:
        response = client.get(OPENAI_MODELS_URL, headers={"Authorization": f"Bearer {api_key}"})
    except httpx.HTTPError as exc:
        return CheckResult("openai", "fail", f"network error ({type(exc).__name__})"), []
    if response.status_code == 401:
        return CheckResult("openai", "fail", "key rejected (HTTP 401)"), []
    if response.status_code != 200:
        return CheckResult("openai", "fail", f"unexpected HTTP {response.status_code}"), []
    models = sorted(str(item["id"]) for item in response.json().get("data", []))
    return CheckResult("openai", "ok", f"key valid; {len(models)} models available"), models


def check_deepgram(api_key: str, client: httpx.Client) -> CheckResult:
    try:
        response = client.get(DEEPGRAM_PROJECTS_URL, headers={"Authorization": f"Token {api_key}"})
    except httpx.HTTPError as exc:
        return CheckResult("deepgram", "fail", f"network error ({type(exc).__name__})")
    if response.status_code == 401:
        return CheckResult("deepgram", "fail", "key rejected (HTTP 401)")
    if response.status_code == 403:
        return CheckResult(
            "deepgram", "warn", "key accepted but cannot list projects; speech APIs may still work"
        )
    if response.status_code != 200:
        return CheckResult("deepgram", "fail", f"unexpected HTTP {response.status_code}")
    projects = response.json().get("projects", [])
    return CheckResult("deepgram", "ok", f"key valid; {len(projects)} project(s)")
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tools/devcli/tests/test_vendors.py`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add tools/devcli/src/hirevion_devcli/vendors.py tools/devcli/tests/test_vendors.py
git commit -m "feat(devcli): validate OpenAI and Deepgram keys without exposing them"
```

---

### Task 5: `hv doctor` and `hv init-env` commands

**Files:**
- Create: `tools/devcli/src/hirevion_devcli/doctor.py`, `tools/devcli/src/hirevion_devcli/cli.py`
- Test: `tools/devcli/tests/test_doctor.py`, `tools/devcli/tests/test_cli.py`

**Interfaces:**
- Consumes: Tasks 2–4.
- Produces:
  - `hirevion_devcli.doctor.gather(repo_root: Path, *, which: Which = find_tool, runner: Runner = run_command, client: httpx.Client | None = None) -> tuple[list[CheckResult], list[str]]`
  - `hirevion_devcli.doctor.summarize_models(models: list[str]) -> list[str]`
  - `hirevion_devcli.cli.app: typer.Typer` with commands `init-env` and `doctor`; `doctor` exits 1 when any check fails.

- [ ] **Step 1: Write the failing tests**

`tools/devcli/tests/test_doctor.py`:
```python
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
    if args[1:2] == ["info"]:
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
```

`tools/devcli/tests/test_cli.py`:
```python
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


def test_doctor_exits_nonzero_when_env_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert ".env" in result.output
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tools/devcli/tests/test_doctor.py tools/devcli/tests/test_cli.py`
Expected: FAIL with `ModuleNotFoundError` for `hirevion_devcli.doctor` and `hirevion_devcli.cli`.

- [ ] **Step 3: Implement `doctor.py` and `cli.py`**

`tools/devcli/src/hirevion_devcli/doctor.py`:
```python
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
```

`tools/devcli/src/hirevion_devcli/cli.py`:
```python
"""Hirevion developer CLI. Run `uv run hv --help`."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import doctor as doctor_checks
from .envfile import init_env

app = typer.Typer(help="Hirevion developer CLI.", no_args_is_help=True)
console = Console()

_STATUS_STYLE = {"ok": "[green]ok[/green]", "warn": "[yellow]warn[/yellow]", "fail": "[red]FAIL[/red]"}


def repo_root() -> Path:
    here = Path.cwd().resolve()
    for candidate in (here, *here.parents):
        if (candidate / "MASTER_IMPLEMENTATION_PLAN.md").exists():
            return candidate
    raise typer.BadParameter("Run this command inside the Hirevion repository.")


@app.command("init-env")
def init_env_command() -> None:
    """Create .env from .env.example with fresh local secrets (never overwrites)."""
    root = repo_root()
    if init_env(root / ".env.example", root / ".env"):
        console.print(
            "Created .env. Add OPENAI_API_KEY and DEEPGRAM_API_KEY to it, "
            "then run `uv run hv doctor`."
        )
    else:
        console.print(".env already exists; left unchanged.")


@app.command()
def doctor() -> None:
    """Check tools, Docker, .env and the AI vendor keys."""
    results, models = doctor_checks.gather(repo_root())
    table = Table(title="Hirevion doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    for result in results:
        table.add_row(result.name, _STATUS_STYLE[result.status], result.detail)
    console.print(table)
    useful = doctor_checks.summarize_models(models)
    if useful:
        console.print("OpenAI models usable by Hirevion: " + ", ".join(useful))
    if any(result.status == "fail" for result in results):
        raise typer.Exit(code=1)
```

- [ ] **Step 4: Run all tests, lint and type-check**

Run: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy tools/devcli/src`
Expected: all tests pass; no lint, format or type errors.

- [ ] **Step 5: Try it for real**

Run: `uv run hv init-env`, add the two keys to `.env`, then `uv run hv doctor`.
Expected: `.env` created once; the doctor table shows each check and lists the OpenAI models; no key value appears anywhere in the output.

- [ ] **Step 6: Commit**

```bash
git add tools/devcli/src/hirevion_devcli/doctor.py tools/devcli/src/hirevion_devcli/cli.py tools/devcli/tests/test_doctor.py tools/devcli/tests/test_cli.py
git commit -m "feat(devcli): add hv doctor and hv init-env commands"
```

---

### Task 6: Secret guard in pre-commit, with hook self-tests

**Files:**
- Create: `tools/hooks/test-hooks.sh`
- Modify: `.githooks/pre-commit`, `.gitattributes`

**Interfaces:**
- Produces: `sh tools/hooks/test-hooks.sh` exits 0 only when every hook behaves as specified; used by CI.

- [ ] **Step 1: Write the failing self-test**

`tools/hooks/test-hooks.sh`:
```sh
#!/bin/sh
# Self-test for the git hooks in .githooks/, run in a throwaway repository.
# Usage: sh tools/hooks/test-hooks.sh
set -u

root=$(cd "$(dirname "$0")/../.." && pwd)
hooks="$root/.githooks"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
failures=0

expect() {
  want=$1
  desc=$2
  shift 2
  "$@" >/dev/null 2>&1
  got=$?
  if [ "$got" -eq "$want" ]; then
    echo "ok   - $desc"
  else
    echo "FAIL - $desc (exit $got, expected $want)"
    failures=$((failures + 1))
  fi
}

repeat() { printf "%${2}s" "" | tr ' ' "$1"; }

export GIT_AUTHOR_NAME="Devaraj-05" GIT_AUTHOR_EMAIL="padma.devaraj1800@gmail.com"
export GIT_COMMITTER_NAME="Devaraj-05" GIT_COMMITTER_EMAIL="padma.devaraj1800@gmail.com"

git init -q "$work/repo"
cd "$work/repo" || exit 1
git config core.hooksPath /dev/null
git commit -q --allow-empty -m "init"

# commit-msg
printf 'docs: add plan\n' > "$work/clean.txt"
printf 'docs: x\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n' > "$work/coauthor.txt"
printf 'feat: x\n\nGenerated with [Claude Code](https://claude.com/claude-code)\n' > "$work/generated.txt"
printf 'docs: explain how Claude Code is used here\n' > "$work/mention.txt"
expect 0 "commit-msg accepts a clean message" sh "$hooks/commit-msg" "$work/clean.txt"
expect 1 "commit-msg rejects a Claude co-author trailer" sh "$hooks/commit-msg" "$work/coauthor.txt"
expect 1 "commit-msg rejects a 'Generated with Claude Code' line" sh "$hooks/commit-msg" "$work/generated.txt"
expect 0 "commit-msg allows a plain mention of Claude" sh "$hooks/commit-msg" "$work/mention.txt"

# pre-commit: identity
expect 0 "pre-commit accepts the project identity" sh "$hooks/pre-commit"
expect 1 "pre-commit rejects another author email" env GIT_AUTHOR_EMAIL=someone@example.com sh "$hooks/pre-commit"
expect 1 "pre-commit rejects another committer name" env GIT_COMMITTER_NAME=Claude sh "$hooks/pre-commit"

# pre-commit: secrets (key-shaped strings are built at runtime so this file stays clean)
printf 'OPENAI_API_KEY=\n' > .env.example
git add .env.example
expect 0 "pre-commit allows .env.example" sh "$hooks/pre-commit"
git reset -q

printf 'PLACEHOLDER=1\n' > .env
git add -f .env
expect 1 "pre-commit blocks a staged .env file" sh "$hooks/pre-commit"
git reset -q
rm -f .env

printf 'client = make("%s")\n' "sk-proj-$(repeat A 48)" > leak.py
git add leak.py
expect 1 "pre-commit blocks an OpenAI-style key" sh "$hooks/pre-commit"
git reset -q
rm -f leak.py

printf '%s_API_KEY=%s\n' "DEEPGRAM" "$(repeat 7 40)" > settings.txt
git add settings.txt
expect 1 "pre-commit blocks a Deepgram key assignment" sh "$hooks/pre-commit"
git reset -q
rm -f settings.txt

# pre-push
zero=0000000000000000000000000000000000000000
foreign=$(GIT_AUTHOR_NAME=Other GIT_AUTHOR_EMAIL=other@example.com \
  GIT_COMMITTER_NAME=Other GIT_COMMITTER_EMAIL=other@example.com \
  git commit-tree "HEAD^{tree}" -p HEAD -m "test: foreign identity")
attributed=$(git commit-tree "HEAD^{tree}" -p HEAD -m "test: attribution" \
  -m "Co-Authored-By: Claude <noreply@anthropic.com>")
clean=$(git commit-tree "HEAD^{tree}" -p HEAD -m "test: clean")
prepush() { printf 'refs/heads/topic %s refs/heads/topic %s\n' "$1" "$2" | sh "$hooks/pre-push"; }
expect 1 "pre-push rejects a foreign-identity commit" prepush "$foreign" "$zero"
expect 1 "pre-push rejects an attributed commit" prepush "$attributed" "$zero"
expect 0 "pre-push accepts a clean commit" prepush "$clean" "$zero"
expect 0 "pre-push ignores branch deletion" prepush "$zero" "$clean"

if [ "$failures" -ne 0 ]; then
  echo "$failures hook test(s) failed"
  exit 1
fi
echo "all hook tests passed"
```

- [ ] **Step 2: Run it to see the secret tests fail**

Run: `sh tools/hooks/test-hooks.sh`
Expected: exit 1; the three "pre-commit blocks …" lines show `FAIL` (the guard doesn't exist yet); every other line shows `ok`.

- [ ] **Step 3: Add the secret guard**

Replace `.githooks/pre-commit` with:
```sh
#!/bin/sh
# Pre-commit guard for this repository (see CLAUDE.md):
#   1. author and committer must be the project identity;
#   2. no .env files or API keys may be committed.

expected_name="Devaraj-05"
expected_email="padma.devaraj1800@gmail.com"

check_ident() {
  role="$1"
  ident="$2"
  name=$(printf '%s\n' "$ident" | sed -E 's/^(.*) <[^>]*>.*$/\1/')
  email=$(printf '%s\n' "$ident" | sed -E 's/^.*<([^>]*)>.*$/\1/')
  if [ "$name" != "$expected_name" ] || [ "$email" != "$expected_email" ]; then
    echo "pre-commit: $role must be '$expected_name <$expected_email>', got '$name <$email>' (see CLAUDE.md)." >&2
    return 1
  fi
}

author=$(git var GIT_AUTHOR_IDENT) || exit 1
committer=$(git var GIT_COMMITTER_IDENT) || exit 1

check_ident "author" "$author" || exit 1
check_ident "committer" "$committer" || exit 1

env_files=$(git diff --cached --name-only --diff-filter=ACMR \
  | grep -E '(^|/)\.env(\.[^/]*)?$' | grep -vE '(^|/)\.env\.example$')
if [ -n "$env_files" ]; then
  echo "pre-commit: refusing to commit env files; secrets belong in the gitignored .env:" >&2
  echo "$env_files" >&2
  exit 1
fi

openai_key='sk-(proj-|svcacct-|admin-)?[A-Za-z0-9_-]{32,}'
key_assignment='(OPENAI|DEEPGRAM|LIVEKIT)_API_(KEY|SECRET)[[:space:]]*[:=][[:space:]]*["'"'"']?[A-Za-z0-9_-]{20,}'
if git diff --cached -U0 --diff-filter=ACMR | grep -E '^\+' | grep -Eq "$openai_key|$key_assignment"; then
  echo "pre-commit: staged changes contain what looks like an API key or secret; keep it in .env." >&2
  exit 1
fi

exit 0
```

Append to `.gitattributes`:
```
*.sh text eol=lf
```

- [ ] **Step 4: Run the self-test to see it pass**

Run: `sh tools/hooks/test-hooks.sh`
Expected: every line `ok`, then `all hook tests passed`, exit 0.

- [ ] **Step 5: Commit**

```bash
git add .githooks/pre-commit .gitattributes
git add --chmod=+x tools/hooks/test-hooks.sh
git commit -m "feat(hooks): block committing .env files and API keys; add hook self-tests"
```

---

### Task 7: Continuous integration

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `tools/hooks/test-hooks.sh`, the uv workspace, `uv.lock`.
- Produces: required checks `hooks`, `python`, `secrets` on pushes to `main` and on pull requests.

- [ ] **Step 1: Create the workflow**

`.github/workflows/ci.yml`:
```yaml
name: ci

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  hooks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - name: Git hook self-tests
        run: sh tools/hooks/test-hooks.sh

  python:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v6
        with:
          python-version: "3.12"
          enable-cache: true
      - run: uv sync --locked
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run mypy tools/devcli/src
      - run: uv run pytest

  secrets:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0
      - uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

- [ ] **Step 2: Verify the same commands pass locally**

Run: `sh tools/hooks/test-hooks.sh`, `uv sync --locked`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy tools/devcli/src`, `uv run pytest`
Expected: all succeed.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: run hook tests, lint, type-check, unit tests and gitleaks"
```

---

### Task 8: ADRs and README

**Files:**
- Create: `docs/architecture/adr/README.md`, `docs/architecture/adr/0000-template.md`, `docs/architecture/adr/0001-monorepo-and-toolchains.md`, `docs/architecture/adr/0002-ai-vendors-openai-deepgram.md`, `README.md`

- [ ] **Step 1: Write the ADRs**

`docs/architecture/adr/0000-template.md`:
```markdown
# ADR-NNNN: <decision in a few words>

- **Status:** Proposed | Accepted | Superseded by ADR-NNNN
- **Date:** YYYY-MM-DD
- **Sub-project:** SP-xx

## Context

What forces the decision: requirements (cite PRD §n), constraints, measurements.

## Decision

What we will do, stated plainly.

## Consequences

What becomes easier, what becomes harder, and what we must now watch.
```

`docs/architecture/adr/0001-monorepo-and-toolchains.md`:
```markdown
# ADR-0001: One monorepo with uv, pnpm and Cargo workspaces

- **Status:** Accepted
- **Date:** 2026-09-28
- **Sub-project:** SP-00a

## Context

Hirevion has two separate applications (Recruitment Platform web, Candidate Windows Desktop AI Interview), the Third-Eye mobile page and a shared Python backend (PRD §5, §93). They share API contracts, event schemas and design tokens, and one developer builds them with Claude Code.

## Decision

- One repository using the PRD §93 top-level layout.
- Python: a uv workspace at the root, Python 3.12, `uv.lock` committed. Shared lint and test settings live in the root `pyproject.toml`.
- TypeScript: pnpm workspaces with Turborepo, added when the first TypeScript package lands (SP-03).
- Rust: a Cargo workspace inside `ai-interviewer-desktop/src-tauri` (SP-08).
- Developer tasks run through one Python CLI, `hv` (`uv run hv --help`).
- Git hooks in `.githooks/` enforce the commit identity, block AI attribution and block secrets; CI runs their self-test.

## Consequences

- One CI pipeline and shared contracts; each application still has its own build and release.
- Fresh clones must run `git config core.hooksPath .githooks` once (README).
- uv manages the Python version, so nothing depends on the system Python.
```

`docs/architecture/adr/0002-ai-vendors-openai-deepgram.md`:
```markdown
# ADR-0002: OpenAI and Deepgram APIs for all AI, from day one

- **Status:** Accepted
- **Date:** 2026-09-28
- **Sub-project:** SP-00a

## Context

The approved master plan first proposed free local models for development. The product owner has OpenAI and Deepgram API keys and chose to use them instead (2026-09-28). The PRD requires an AI provider abstraction (§78), streaming speech (§33, §42) and auditable AI use (§79).

## Decision

- Profiles: `vendor` (OpenAI for LLM, embeddings, vision and a text-to-speech fallback; Deepgram for streaming speech-to-text and Aura-2 text-to-speech) for development and production, and `mock` (deterministic fakes) for CI and load tests.
- Every AI call goes through `hirevion_core.ai` and is recorded with model, prompt and rubric versions, tokens, latency and cost.
- Model names live in configuration; the SP-00 benchmark picks them from the models the keys can use.
- Keys live only in the gitignored root `.env` (Key Vault in the cloud). Never in the repo, the desktop app or the web bundle.
- Development uses synthetic data. Real candidate data goes to the vendors only after DPAs are signed and retention / model-improvement opt-outs are set.

## Consequences

- Real model quality and latency from the first day; no GPU needed.
- Every developer run costs money: metering and per-organisation budgets are built in from SP-01, and CI uses `mock`.
- Latency depends on the network path from India to the vendors; SP-00 measures it, and fallbacks (Azure OpenAI, OpenAI speech) cover outages.
- ElevenLabs or Cartesia can be added later as text-to-speech providers without code changes outside the provider layer.
```

`docs/architecture/adr/README.md`:
```markdown
# Architecture decision records

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-monorepo-and-toolchains.md) | One monorepo with uv, pnpm and Cargo workspaces | Accepted |
| [0002](0002-ai-vendors-openai-deepgram.md) | OpenAI and Deepgram APIs for all AI, from day one | Accepted |

New decisions copy [0000-template.md](0000-template.md) and take the next number.
```

- [ ] **Step 2: Write the README**

`README.md`:
```markdown
# Hirevion

Enterprise AI recruitment and interview platform:

- **Recruitment Platform** (web): jobs, resume screening and ranking, candidates, interview configuration, live monitoring, reports, analytics and administration.
- **Candidate Windows Desktop AI Interview** (`AI-Interview.exe`): AI voice interview, coding, recording and proctoring.
- **Third-Eye**: a phone browser page that adds a second camera angle.
- **Backend**: the shared Python services behind all three.

Key documents:

- Requirements: [AI_Recruitment_Platform_Complete_PRD.md](AI_Recruitment_Platform_Complete_PRD.md)
- Architecture, sub-projects and schedule: [MASTER_IMPLEMENTATION_PLAN.md](MASTER_IMPLEMENTATION_PLAN.md)
- Decisions: [docs/architecture/adr](docs/architecture/adr/README.md)
- Rules for contributors (human or AI): [CLAUDE.md](CLAUDE.md)

## Prerequisites (Windows 11)

| Tool | Version | Needed for |
|---|---|---|
| Git for Windows | 2.40+ | everything |
| Docker Desktop (WSL2) | recent | the local stack |
| uv | 0.5+ | the Python toolchain (uv installs Python 3.12 itself) |
| Node.js | 24 LTS | the web, desktop and third-eye apps |
| pnpm | 9+ | TypeScript workspaces |
| Rust via rustup, with Visual Studio 2022 Build Tools (C++ workload) | Rust 1.85+ | the desktop app |

## First-time setup

1. `git config core.hooksPath .githooks` turns on the repository's git guards.
2. `uv sync` creates the Python environment.
3. `uv run hv init-env` creates `.env` with fresh local secrets.
4. Add `OPENAI_API_KEY` and `DEEPGRAM_API_KEY` to `.env`. It is gitignored; never commit it.
5. `uv run hv doctor` checks your tools, Docker and API keys.

## Everyday commands

| Command | What it does |
|---|---|
| `uv run hv --help` | Lists developer commands |
| `uv run pytest` | Runs the Python tests |
| `uv run ruff check .` | Lints the Python code |
| `sh tools/hooks/test-hooks.sh` | Tests the git hooks |
```

- [ ] **Step 3: Commit**

```bash
git add README.md docs/architecture/adr
git commit -m "docs: add README and first architecture decision records"
```

---

## Definition of done for SP-00a

- `uv sync --locked`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy tools/devcli/src` and `uv run pytest` all pass.
- `sh tools/hooks/test-hooks.sh` passes.
- `uv run hv doctor` reports tools and Docker, and validates both API keys once they're in `.env`, without printing them.
- CI is green on the pushed branch.
