import httpx
import respx

from hirevion_devcli.vendors import (
    DEEPGRAM_PROJECTS_URL,
    GEMINI_MODELS_URL,
    OPENAI_MODELS_URL,
    check_deepgram,
    check_gemini,
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
