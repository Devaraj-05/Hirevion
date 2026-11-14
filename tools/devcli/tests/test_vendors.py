import httpx
import respx

from hirevion_devcli.vendors import (
    DEEPGRAM_PROJECTS_URL,
    GEMINI_MODELS_URL,
    NEMOTRON_CHAT_URL,
    OPENAI_MODELS_URL,
    OPENROUTER_KEY_URL,
    check_deepgram,
    check_gemini,
    check_nemotron,
    check_openai,
    check_openrouter,
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


@respx.mock
def test_openrouter_valid_key_reports_its_credit_without_the_key() -> None:
    route = respx.get(OPENROUTER_KEY_URL).mock(
        return_value=httpx.Response(
            200, json={"data": {"label": "sk-or-v1-abc...", "usage": 0.25, "limit": 10}}
        )
    )
    with httpx.Client() as client:
        result = check_openrouter(KEY, client)
    assert result.status == "ok"
    assert "sk-or" not in result.detail and KEY not in result.detail
    assert route.calls.last.request.headers["Authorization"] == f"Bearer {KEY}"


@respx.mock
def test_openrouter_rejected_key_fails() -> None:
    respx.get(OPENROUTER_KEY_URL).mock(return_value=httpx.Response(401, json={"error": {}}))
    with httpx.Client() as client:
        result = check_openrouter(KEY, client)
    assert result.status == "fail" and "401" in result.detail


@respx.mock
def test_nemotron_key_and_model_answer_one_token() -> None:
    route = respx.post(NEMOTRON_CHAT_URL).mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})
    )
    with httpx.Client() as client:
        result = check_nemotron(KEY, "nvidia/test-model", client)
    assert result.status == "ok" and "nvidia/test-model" in result.detail
    sent = route.calls.last.request
    assert sent.headers["Authorization"] == f"Bearer {KEY}"
    body = __import__("json").loads(sent.content)
    assert body["model"] == "nvidia/test-model" and body["max_tokens"] == 1


@respx.mock
def test_nemotron_names_a_rejected_key_or_an_unknown_model() -> None:
    respx.post(NEMOTRON_CHAT_URL).mock(
        side_effect=[httpx.Response(401, json={}), httpx.Response(404, json={})]
    )
    with httpx.Client() as client:
        rejected = check_nemotron(KEY, "nvidia/test-model", client)
        unknown = check_nemotron(KEY, "nvidia/test-model", client)
    assert rejected.status == "fail" and "key rejected" in rejected.detail
    assert unknown.status == "fail" and "nvidia/test-model" in unknown.detail
    assert KEY not in rejected.detail + unknown.detail
