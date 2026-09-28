# SP-00a.1 Gemini Development Provider and `hv env-sync` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Gemini (the product owner's paid key) the LLM for development and testing, keep OpenAI as the production LLM, and add `hv env-sync` so new settings reach an existing `.env` without touching its values.

**Architecture:** Required development keys become `GEMINI_API_KEY` and `DEEPGRAM_API_KEY`; `OPENAI_API_KEY` is optional locally. `hv doctor` checks each vendor independently whenever its key is present, so a missing key never hides the result for another. A pure `sync_env()` computes the lines to append; the CLI writes them.

**Tech Stack:** Python 3.12, httpx, respx, Typer, pytest.

## Global Constraints

- Everything in `MASTER_IMPLEMENTATION_PLAN.md` §13 and in the SP-00a plan's Global Constraints applies.
- The Gemini key is sent only in the `x-goog-api-key` header; no result, log line or error message contains any key.
- Development uses Gemini through its OpenAI-compatible endpoint where possible, so the same client code serves Gemini (development) and OpenAI (production).

## File Structure

| Path | Change |
|---|---|
| `tools/devcli/src/hirevion_devcli/envfile.py` | `REQUIRED_KEYS` → Gemini + Deepgram; add `sync_env()` |
| `tools/devcli/src/hirevion_devcli/vendors.py` | add `GEMINI_MODELS_URL`, `check_gemini()` |
| `tools/devcli/src/hirevion_devcli/doctor.py` | per-vendor checks; models grouped by provider; Gemini families in the summary |
| `tools/devcli/src/hirevion_devcli/cli.py` | `env-sync` command; per-provider model lines |
| `tools/devcli/tests/*` | tests for all of the above |
| `.env.example` | `GEMINI_API_KEY` (required), `OPENAI_API_KEY` (production) |
| `pyproject.toml` | `link-mode = "copy"` (uv cache on C:, repo on D:) |
| `docs/architecture/adr/0003-gemini-for-development.md`, ADR index | record the decision |
| `MASTER_IMPLEMENTATION_PLAN.md`, `CLAUDE.md`, `README.md` | reflect Gemini (development) / OpenAI (production) |

---

### Task 1: Required keys and `sync_env()`

**Interfaces:**
- Produces: `REQUIRED_KEYS = ("GEMINI_API_KEY", "DEEPGRAM_API_KEY")`; `sync_env(example_text: str, env_text: str, generated: dict[str, str]) -> tuple[str, list[str]]`: appends every key that is in the example but not in the env text, using the example's value, else the generated secret, else empty; returns the new text and the added key names; returns the env text unchanged and `[]` when nothing is missing.

- [ ] **Step 1: Update and add failing tests** in `tools/devcli/tests/test_envfile.py`:

```python
def test_missing_required_lists_empty_and_placeholder_keys() -> None:
    values = {"GEMINI_API_KEY": "changeme", "DEEPGRAM_API_KEY": "k" * 40}
    assert missing_required(values) == ["GEMINI_API_KEY"]
    assert missing_required({}) == ["GEMINI_API_KEY", "DEEPGRAM_API_KEY"]


def test_sync_env_appends_only_missing_keys() -> None:
    example = "A=\nB=default\nPOSTGRES_PASSWORD=\nC=\n"
    env = "A=mine\n"
    new_text, added = sync_env(example, env, {"POSTGRES_PASSWORD": "p" * 32})
    assert added == ["B", "POSTGRES_PASSWORD", "C"]
    assert parse_env(new_text) == {"A": "mine", "B": "default", "POSTGRES_PASSWORD": "p" * 32, "C": ""}
    assert new_text.startswith("A=mine\n")


def test_sync_env_is_a_no_op_when_complete() -> None:
    env = "A=mine\nB=x\n"
    assert sync_env("A=\nB=\n", env, {}) == (env, [])


def test_sync_env_handles_env_without_trailing_newline() -> None:
    new_text, added = sync_env("A=\nB=\n", "A=mine", {})
    assert added == ["B"]
    assert parse_env(new_text) == {"A": "mine", "B": ""}
```

Update `tools/devcli/tests/test_checks.py::test_env_check` to use `GEMINI_API_KEY` instead of `OPENAI_API_KEY`.

- [ ] **Step 2: Run** `uv run pytest tools/devcli/tests/test_envfile.py tools/devcli/tests/test_checks.py` — expect `ImportError` for `sync_env` (collection error).

- [ ] **Step 3: Implement** in `envfile.py`:

```python
REQUIRED_KEYS: tuple[str, ...] = ("GEMINI_API_KEY", "DEEPGRAM_API_KEY")


def sync_env(example_text: str, env_text: str, generated: dict[str, str]) -> tuple[str, list[str]]:
    """Append keys that are in the example but missing from the env text; keep existing values."""
    existing = parse_env(env_text)
    added: list[str] = []
    lines: list[str] = []
    for key, example_value in parse_env(example_text).items():
        if key in existing:
            continue
        added.append(key)
        lines.append(f"{key}={example_value or generated.get(key, '')}")
    if not added:
        return env_text, []
    base = env_text if not env_text or env_text.endswith("\n") else env_text + "\n"
    return base + "# Added by `hv env-sync`\n" + "\n".join(lines) + "\n", added
```

- [ ] **Step 4: Run** the same tests — expect all pass. **Step 5: Commit** `feat(devcli): require Gemini and Deepgram keys; add sync_env`.

### Task 2: `check_gemini()`

**Interfaces:**
- Produces: `GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000"`; `check_gemini(api_key: str, client: httpx.Client) -> tuple[CheckResult, list[str]]` returning model names without the `models/` prefix, sorted.

- [ ] **Step 1: Add failing tests** to `tools/devcli/tests/test_vendors.py`:

```python
@respx.mock
def test_gemini_valid_key_returns_models() -> None:
    route = respx.get(GEMINI_MODELS_URL).mock(
        return_value=httpx.Response(
            200, json={"models": [{"name": "models/gemini-b"}, {"name": "models/gemini-a"}]}
        )
    )
    with httpx.Client() as client:
        result, models = check_gemini(KEY, client)
    assert result.status == "ok"
    assert models == ["gemini-a", "gemini-b"]
    assert route.calls.last.request.headers["x-goog-api-key"] == KEY
    assert KEY not in str(route.calls.last.request.url)


@respx.mock
def test_gemini_rejected_key_fails_without_leaking_it() -> None:
    respx.get(GEMINI_MODELS_URL).mock(return_value=httpx.Response(400, json={"error": {}}))
    with httpx.Client() as client:
        result, models = check_gemini(KEY, client)
    assert result.status == "fail"
    assert KEY not in result.detail
    assert models == []


@respx.mock
def test_gemini_network_error_fails() -> None:
    respx.get(GEMINI_MODELS_URL).mock(side_effect=httpx.ConnectError("down"))
    with httpx.Client() as client:
        result, _ = check_gemini(KEY, client)
    assert result.status == "fail"
    assert "network" in result.detail
```

- [ ] **Step 2: Run** — expect `ImportError`. **Step 3: Implement** in `vendors.py`:

```python
GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000"


def check_gemini(api_key: str, client: httpx.Client) -> tuple[CheckResult, list[str]]:
    try:
        response = client.get(GEMINI_MODELS_URL, headers={"x-goog-api-key": api_key})
    except httpx.HTTPError as exc:
        return CheckResult("gemini", "fail", f"network error ({type(exc).__name__})"), []
    if response.status_code in (400, 401, 403):
        return CheckResult("gemini", "fail", f"key rejected (HTTP {response.status_code})"), []
    if response.status_code != 200:
        return CheckResult("gemini", "fail", f"unexpected HTTP {response.status_code}"), []
    names = (str(item["name"]).removeprefix("models/") for item in response.json().get("models", []))
    models = sorted(names)
    return CheckResult("gemini", "ok", f"key valid; {len(models)} models available"), models
```

- [ ] **Step 4: Run** — expect pass. **Step 5: Commit** `feat(devcli): validate the Gemini key`.

### Task 3: Per-vendor doctor checks

**Interfaces:**
- Produces: `gather(...) -> tuple[list[CheckResult], dict[str, list[str]]]` — tools, then `.env`, then `gemini` (if its key is set), `deepgram` (if set), `openai` (if set); models keyed by provider. `summarize_models()` also keeps `gemini-` families.

- [ ] **Step 1: Replace the vendor tests** in `tools/devcli/tests/test_doctor.py` (keep `runner` and the no-env test, which now expects `models == {}`):

```python
GEMINI_KEY = "gemini-test-" + "g" * 40


def write_env(root: Path, **keys: str) -> None:
    (root / ".env").write_text(
        "".join(f"{name}={value}\n" for name, value in keys.items()), encoding="utf-8"
    )


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
        tmp_path, GEMINI_API_KEY=GEMINI_KEY, DEEPGRAM_API_KEY=DEEPGRAM_KEY, OPENAI_API_KEY=OPENAI_KEY
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
```

and extend the summary test with `"gemini-2.5-flash"`, `"gemini-embedding-001"` (kept) and `"imagen-4.0-generate-001"` (dropped).

- [ ] **Step 2: Run** — expect failures (`gemini` missing, models is a list). **Step 3: Implement** `gather()`:

```python
_MODEL_PREFIXES = ("gemini-", "gpt-", "o1", "o3", "o4", "text-embedding-", "tts-", "whisper-")


def gather(
    repo_root: Path,
    *,
    which: Which = find_tool,
    runner: Runner = run_command,
    client: httpx.Client | None = None,
) -> tuple[list[CheckResult], dict[str, list[str]]]:
    results = [...]  # unchanged tool checks
    env_path = repo_root / ".env"
    values = parse_env(env_path.read_text(encoding="utf-8")) if env_path.exists() else None
    results.append(check_env(values))
    models: dict[str, list[str]] = {}
    if values is None:
        return results, models

    def has(key: str) -> bool:
        return not is_placeholder(values.get(key, ""))

    if not any(has(key) for key in ("GEMINI_API_KEY", "DEEPGRAM_API_KEY", "OPENAI_API_KEY")):
        return results, models
    http = client if client is not None else httpx.Client(timeout=20)
    try:
        if has("GEMINI_API_KEY"):
            gemini_result, models["gemini"] = check_gemini(values["GEMINI_API_KEY"], http)
            results.append(gemini_result)
        if has("DEEPGRAM_API_KEY"):
            results.append(check_deepgram(values["DEEPGRAM_API_KEY"], http))
        if has("OPENAI_API_KEY"):
            openai_result, models["openai"] = check_openai(values["OPENAI_API_KEY"], http)
            results.append(openai_result)
    finally:
        if client is None:
            http.close()
    return results, models
```

In `cli.py` print one line per provider: `f"{provider} models usable by Hirevion: ..."`.

- [ ] **Step 4: Run** all tests, ruff and mypy — expect clean. **Step 5: Commit** `feat(devcli): check each AI vendor independently, Gemini first`.

### Task 4: `hv env-sync`

- [ ] **Step 1: Failing test** in `tools/devcli/tests/test_cli.py`:

```python
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
```

- [ ] **Step 2: Run** — expect exit code 2 (no such command). **Step 3: Implement** the command:

```python
@app.command("env-sync")
def env_sync_command() -> None:
    """Add settings that are new in .env.example to .env (existing values are kept)."""
    root = repo_root()
    env_path = root / ".env"
    if not env_path.exists():
        console.print(".env is missing; run `uv run hv init-env` first.")
        raise typer.Exit(code=1)
    new_text, added = sync_env(
        (root / ".env.example").read_text(encoding="utf-8"),
        env_path.read_text(encoding="utf-8"),
        generate_local_secrets(),
    )
    if added:
        env_path.write_text(new_text, encoding="utf-8")
        console.print("Added to .env: " + ", ".join(added))
    else:
        console.print(".env is already up to date.")
```

- [ ] **Step 4: Run** — expect pass. **Step 5: Commit** `feat(devcli): add hv env-sync`.

### Task 5: Settings template, uv link mode and docs

- [ ] `.env.example`: AI section becomes `GEMINI_API_KEY=` (required for development and testing), `DEEPGRAM_API_KEY=` (required), `OPENAI_API_KEY=` (production; optional locally).
- [ ] `pyproject.toml`: `[tool.uv]` gains `link-mode = "copy"`.
- [ ] ADR-0003 "Gemini for development and testing, OpenAI for production" (Accepted, 2026-09-28) and the ADR index row.
- [ ] `MASTER_IMPLEMENTATION_PLAN.md` §0, D6, §5.1, §5.3 and §17; `CLAUDE.md` working rules; `README.md` setup step 4 — all say Gemini (development/testing), OpenAI (production), Deepgram (speech).
- [ ] Run `uv run hv env-sync` to add `GEMINI_API_KEY=` to the local `.env`, then run the full verification (pytest, ruff, mypy, hook self-test).
- [ ] Commit `docs: use Gemini for development and OpenAI for production`.
