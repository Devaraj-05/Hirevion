"""Live checks for the AI vendor keys. Never include a key in any result."""

from __future__ import annotations

import httpx

from .checks import CheckResult

OPENAI_MODELS_URL = "https://api.openai.com/v1/models"
DEEPGRAM_PROJECTS_URL = "https://api.deepgram.com/v1/projects"
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
    listed = response.json().get("models", [])
    models = sorted(str(item["name"]).removeprefix("models/") for item in listed)
    return CheckResult("gemini", "ok", f"key valid; {len(models)} models available"), models


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


OPENROUTER_KEY_URL = "https://openrouter.ai/api/v1/key"
NEMOTRON_CHAT_URL = "https://integrate.api.nvidia.com/v1/chat/completions"


def check_openrouter(api_key: str, client: httpx.Client) -> CheckResult:
    """OpenRouter's key endpoint answers only a valid key and spends nothing."""
    try:
        response = client.get(OPENROUTER_KEY_URL, headers={"Authorization": f"Bearer {api_key}"})
    except httpx.HTTPError as exc:
        return CheckResult("openrouter", "fail", f"network error ({type(exc).__name__})")
    if response.status_code in (401, 403):
        return CheckResult("openrouter", "fail", f"key rejected (HTTP {response.status_code})")
    if response.status_code != 200:
        return CheckResult("openrouter", "fail", f"unexpected HTTP {response.status_code}")
    # The label can hold a prefix of the key, so only the numbers are reported.
    data = response.json().get("data", {})
    limit = data.get("limit")
    spent = f"${float(data.get('usage') or 0):.2f} spent"
    return CheckResult(
        "openrouter", "ok", f"key valid; {spent}" + (f" of ${float(limit):.2f}" if limit else "")
    )


def check_nemotron(api_key: str, model: str, client: httpx.Client) -> CheckResult:
    """A one-token answer from the interview model proves the key and the model together."""
    try:
        response = client.post(
            NEMOTRON_CHAT_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Reply with OK."}],
                "max_tokens": 1,
            },
            timeout=60,
        )
    except httpx.HTTPError as exc:
        return CheckResult("nemotron", "fail", f"network error ({type(exc).__name__})")
    if response.status_code in (401, 403):
        return CheckResult("nemotron", "fail", f"key rejected (HTTP {response.status_code})")
    if response.status_code == 404:
        return CheckResult("nemotron", "fail", f"{model} isn't available to this key (HTTP 404)")
    if response.status_code != 200:
        return CheckResult("nemotron", "fail", f"unexpected HTTP {response.status_code}")
    return CheckResult("nemotron", "ok", f"key valid; {model} answers")
