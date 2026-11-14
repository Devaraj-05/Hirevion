"""The `dev` profile's two providers on the wire (ADR-0034): OpenRouter answers the screening
tasks with a strict JSON schema, only through providers that honour it and don't train on the
data; NVIDIA Nemotron answers the interview tasks with `guided_json`, the structured output its
hosted endpoint applies. Every call is recorded under the provider that served it."""

import json
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import httpx
import pytest
import respx
from pydantic import BaseModel, SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.ai import build_ai, openai_compat
from hirevion_core.ai.mock import MOCK_PRICES
from hirevion_core.ai.settings import AiSettings
from hirevion_core.ai.types import AiContext, AiRequestError
from hirevion_core.db.session import Database

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]
OPENROUTER = "https://openrouter.test/api/v1"
NEMOTRON = "https://nemotron.test/v1"
SETTINGS = AiSettings(
    profile="dev",
    openrouter_api_key="o-key",  # type: ignore[arg-type]
    nemotron_api_key="n-key",  # type: ignore[arg-type]
    deepgram_api_key="d-key",  # type: ignore[arg-type]
    openrouter_base_url=OPENROUTER,
    nemotron_base_url=NEMOTRON,
    openrouter_model_fast="router/fast",
    openrouter_model_strong="router/strong",
    openrouter_embedding_model="router/embed",
    openrouter_vision_model="router/vision",
    nemotron_model_fast="nvidia/fast",
    nemotron_model_strong="nvidia/strong",
    nemotron_embedding_model="nvidia/embed",
    nemotron_vision_model="nvidia/vision",
    embedding_dimensions=3,
    max_output_tokens=1234,
)


class Verdict(BaseModel):
    summary: str
    score: int


def completion(content: str, model: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "c1",
            "object": "chat.completion",
            "created": 1,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        },
    )


def problem(status: int) -> httpx.Response:
    return httpx.Response(status, json={"error": {"message": "refused", "code": status}})


def sent(route: respx.Route) -> dict[str, Any]:
    return json.loads(route.calls.last.request.content)


async def providers(admin_engine: AsyncEngine, org: UUID) -> list[tuple[str, str]]:
    async with admin_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT purpose, provider FROM ai_invocations WHERE organization_id = :org "
                "ORDER BY occurred_at"
            ),
            {"org": org},
        )
        return [(row.purpose, row.provider) for row in result]


@respx.mock
async def test_screening_goes_to_openrouter_and_interviews_to_nemotron(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    org = await make_organization("Routing")
    router = respx.post(f"{OPENROUTER}/chat/completions").mock(
        return_value=completion('{"summary": "fits", "score": 4}', "router/strong")
    )
    nvidia = respx.post(f"{NEMOTRON}/chat/completions").mock(
        return_value=completion('{"summary": "deep answer", "score": 5}', "nvidia/strong")
    )
    ai = build_ai(SETTINGS, app_db, MOCK_PRICES)
    try:
        messages = [{"role": "user", "content": "<resume>x</resume>"}]
        parsed = await ai.llm.complete(AiContext(org, "resume.parse"), messages, Verdict)
        judged = await ai.llm.complete(
            AiContext(org, "evaluation.question"), messages, Verdict, tier="fast"
        )
    finally:
        await ai.aclose()

    assert parsed.value == Verdict(summary="fits", score=4)
    assert judged.value == Verdict(summary="deep answer", score=5)

    screening = sent(router)
    assert screening["model"] == "router/strong"
    assert screening["response_format"]["type"] == "json_schema"
    assert screening["response_format"]["json_schema"]["strict"] is True
    assert screening["provider"] == {"require_parameters": True, "data_collection": "deny"}
    # A cap on every answer: OpenRouter reserves credit for the model's whole output otherwise.
    assert screening["max_tokens"] == 1234
    assert router.calls.last.request.headers["authorization"] == "Bearer o-key"

    interview = sent(nvidia)
    assert interview["model"] == "nvidia/fast"
    assert "response_format" not in interview
    assert interview["max_tokens"] == 1234
    assert interview["guided_json"]["properties"].keys() == {"summary", "score"}
    assert interview["guided_json"]["additionalProperties"] is False
    assert nvidia.calls.last.request.headers["authorization"] == "Bearer n-key"

    assert await providers(admin_engine, org) == [
        ("resume.parse", "openrouter"),
        ("evaluation.question", "nemotron"),
    ]


@respx.mock
async def test_embeddings_come_from_nemotron_and_page_reading_from_openrouter(
    app_db: Database, make_organization: MakeOrganization
) -> None:
    org = await make_organization("RoutingEmbed")
    embed = respx.post(f"{NEMOTRON}/embeddings").mock(
        return_value=httpx.Response(
            200,
            json={
                "object": "list",
                "model": "nvidia/embed",
                "data": [{"object": "embedding", "index": 0, "embedding": [1.0, 0.0, 0.0]}],
                "usage": {"prompt_tokens": 3, "total_tokens": 3},
            },
        )
    )
    page = respx.post(f"{OPENROUTER}/chat/completions").mock(
        return_value=completion('{"text": "HIREVION", "confidence": 0.9}', "router/vision")
    )
    ai = build_ai(SETTINGS, app_db, MOCK_PRICES)
    try:
        vectors = await ai.embeddings.embed(AiContext(org, "resume.embed"), ["Python engineer"])
        await ai.embeddings.embed(AiContext(org, "jd.embed"), ["We need a Python engineer"])
        await ai.embeddings.embed(AiContext(org, "job.embed"), ["Backend Engineer"])
        read = await ai.ocr.read_page(AiContext(org, "resume.ocr"), b"\x89PNG", "image/png")
    finally:
        await ai.aclose()

    assert vectors.vectors == [[1.0, 0.0, 0.0]]
    # One embedding model for every stored vector, so they stay comparable (ADR-0034).
    bodies = [json.loads(call.request.content) for call in embed.calls]
    assert {body["model"] for body in bodies} == {"nvidia/embed"}
    assert {body["dimensions"] for body in bodies} == {3}
    # NVIDIA's retrieval models are asymmetric: a resume is a "passage", and the job it is
    # matched against is the "query".
    assert [body["input_type"] for body in bodies] == ["passage", "query", "query"]
    assert embed.calls.last.request.headers["authorization"] == "Bearer n-key"
    assert read.text == "HIREVION" and sent(page)["model"] == "router/vision"


@respx.mock
async def test_screening_falls_back_to_nemotron_when_openrouter_cannot_serve(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    """Product-owner decision, 2026-11-14: if OpenRouter isn't working, use Nemotron."""
    org = await make_organization("RoutingFallback")
    router = respx.post(f"{OPENROUTER}/chat/completions").mock(return_value=problem(402))
    nvidia = respx.post(f"{NEMOTRON}/chat/completions").mock(
        side_effect=[
            completion('{"summary": "fits", "score": 4}', "nvidia/strong"),
            completion('{"text": "HIREVION", "confidence": 0.9}', "nvidia/vision"),
        ]
    )
    ai = build_ai(SETTINGS, app_db, MOCK_PRICES)
    try:
        messages = [{"role": "user", "content": "<resume>x</resume>"}]
        assessed = await ai.llm.complete(AiContext(org, "screening.assess"), messages, Verdict)
        read = await ai.ocr.read_page(AiContext(org, "resume.ocr"), b"\x89PNG", "image/png")
    finally:
        await ai.aclose()

    assert assessed.value == Verdict(summary="fits", score=4)
    assert assessed.model == "nvidia/strong"
    assert read.text == "HIREVION"
    assert [json.loads(call.request.content)["model"] for call in nvidia.calls] == [
        "nvidia/strong",
        "nvidia/vision",
    ]
    # After OpenRouter's refusal it rests for the cooldown: page reading goes straight on.
    assert router.call_count == 1
    # Every attempt is on record: OpenRouter's refusal (no credit), then Nemotron's answers.
    assert await providers(admin_engine, org) == [
        ("screening.assess", "openrouter"),
        ("screening.assess", "nemotron"),
        ("resume.ocr", "nemotron"),
    ]


@respx.mock
async def test_a_refused_request_does_not_fall_back(
    app_db: Database, make_organization: MakeOrganization
) -> None:
    org = await make_organization("RoutingRefused")
    respx.post(f"{OPENROUTER}/chat/completions").mock(return_value=problem(400))
    nvidia = respx.post(f"{NEMOTRON}/chat/completions").mock(
        return_value=completion('{"summary": "x", "score": 1}', "nvidia/strong")
    )
    ai = build_ai(SETTINGS, app_db, MOCK_PRICES)
    try:
        with pytest.raises(AiRequestError):
            await ai.llm.complete(
                AiContext(org, "resume.parse"), [{"role": "user", "content": "x"}], Verdict
            )
    finally:
        await ai.aclose()
    # A bad request is a bug to fix, not an outage: sending it elsewhere would hide it.
    assert not nvidia.called


@respx.mock
async def test_screening_can_run_on_nemotron_alone(
    app_db: Database, make_organization: MakeOrganization
) -> None:
    org = await make_organization("RoutingNemotronOnly")
    router = respx.post(f"{OPENROUTER}/chat/completions").mock(return_value=problem(500))
    nvidia = respx.post(f"{NEMOTRON}/chat/completions").mock(
        return_value=completion('{"text": "HIREVION", "confidence": 0.9}', "nvidia/vision")
    )
    settings = SETTINGS.model_copy(update={"screening_provider": "nemotron"})
    ai = build_ai(settings, app_db, MOCK_PRICES)
    try:
        read = await ai.ocr.read_page(AiContext(org, "resume.ocr"), b"\x89PNG", "image/png")
    finally:
        await ai.aclose()
    assert read.text == "HIREVION" and sent(nvidia)["model"] == "nvidia/vision"
    assert not router.called


@pytest.mark.parametrize(
    ("missing", "named"),
    [("nemotron_api_key", "NEMOTRON_API_KEY"), ("deepgram_api_key", "DEEPGRAM_API_KEY")],
)
def test_a_missing_key_is_named_before_any_client_opens(
    app_db: Database, monkeypatch: pytest.MonkeyPatch, missing: str, named: str
) -> None:
    opened: list[dict[str, Any]] = []
    monkeypatch.setattr(openai_compat, "AsyncOpenAI", lambda **kwargs: opened.append(kwargs))
    settings = SETTINGS.model_copy(update={missing: SecretStr("")})
    with pytest.raises(ValueError, match=named):
        build_ai(settings, app_db, MOCK_PRICES)
    # Nothing to close: the callers carry on without AI, so an opened client would leak.
    assert opened == []


@respx.mock
async def test_openai_takes_the_cap_as_max_completion_tokens(
    app_db: Database, make_organization: MakeOrganization
) -> None:
    org = await make_organization("RoutingOpenAI")
    route = respx.post("https://openai.test/v1/chat/completions").mock(
        return_value=completion('{"summary": "ok", "score": 1}', "gpt-test")
    )
    settings = AiSettings(
        profile="production",
        openai_api_key="p-key",  # type: ignore[arg-type]
        openai_base_url="https://openai.test/v1",
        deepgram_api_key="d-key",  # type: ignore[arg-type]
        max_output_tokens=1234,
    )
    ai = build_ai(settings, app_db, MOCK_PRICES)
    try:
        await ai.llm.complete(
            AiContext(org, "screening.rank"), [{"role": "user", "content": "x"}], Verdict
        )
    finally:
        await ai.aclose()
    body = sent(route)
    # OpenAI's newer models refuse max_tokens and take max_completion_tokens.
    assert body["max_completion_tokens"] == 1234 and "max_tokens" not in body
