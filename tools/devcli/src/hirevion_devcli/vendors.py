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
