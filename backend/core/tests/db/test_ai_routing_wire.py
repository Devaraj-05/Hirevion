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
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.ai import build_ai
from hirevion_core.ai.mock import MOCK_PRICES
from hirevion_core.ai.settings import AiSettings
from hirevion_core.ai.types import AiContext
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
    embedding_dimensions=3,
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
    assert router.calls.last.request.headers["authorization"] == "Bearer o-key"

    interview = sent(nvidia)
    assert interview["model"] == "nvidia/fast"
    assert "response_format" not in interview
    assert interview["guided_json"]["properties"].keys() == {"summary", "score"}
    assert interview["guided_json"]["additionalProperties"] is False
    assert nvidia.calls.last.request.headers["authorization"] == "Bearer n-key"

    assert await providers(admin_engine, org) == [
        ("resume.parse", "openrouter"),
        ("evaluation.question", "nemotron"),
    ]


@respx.mock
async def test_resume_embeddings_and_page_reading_go_to_openrouter(
    app_db: Database, make_organization: MakeOrganization
) -> None:
    org = await make_organization("RoutingEmbed")
    embed = respx.post(f"{OPENROUTER}/embeddings").mock(
        return_value=httpx.Response(
            200,
            json={
                "object": "list",
                "model": "router/embed",
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
        vectors = await ai.embeddings.embed(AiContext(org, "resume.parse"), ["Python engineer"])
        read = await ai.ocr.read_page(AiContext(org, "resume.ocr"), b"\x89PNG", "image/png")
    finally:
        await ai.aclose()

    assert vectors.vectors == [[1.0, 0.0, 0.0]]
    assert sent(embed)["model"] == "router/embed"
    assert sent(embed)["dimensions"] == 3
    assert read.text == "HIREVION" and sent(page)["model"] == "router/vision"


def test_the_dev_profile_names_the_key_it_is_missing(app_db: Database) -> None:
    settings = SETTINGS.model_copy(
        update={"nemotron_api_key": SETTINGS.nemotron_api_key.__class__("")}
    )
    with pytest.raises(ValueError, match="NEMOTRON_API_KEY"):
        build_ai(settings, app_db, MOCK_PRICES)
