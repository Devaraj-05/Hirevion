"""Contract tests for the OpenAI-compatible backend (Gemini in `dev`, OpenAI in `production`).

The vendor is replaced at the HTTP level with respx, so these check the exact requests sent
and how responses and failures are handled, without network or cost.
"""

import base64
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

from hirevion_core.ai.mock import MOCK_PRICES
from hirevion_core.ai.openai_compat import OpenAICompatible
from hirevion_core.ai.recorder import Recorder
from hirevion_core.ai.settings import AiSettings
from hirevion_core.ai.types import (
    AiContext,
    AiOutputInvalid,
    AiRequestError,
    AiUnavailable,
)
from hirevion_core.db.session import Database

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]
BASE = "https://llm.test/v1"
SETTINGS = AiSettings(
    profile="dev",
    gemini_api_key="test-key",  # type: ignore[arg-type]
    gemini_base_url=BASE,
    llm_model_fast="fast-model",
    llm_model_strong="strong-model",
    embedding_model="embed-model",
    vision_model="vision-model",
)


class Summary(BaseModel):
    headline: str
    score: int


def completion(content: str, model: str = "strong-model-001") -> httpx.Response:
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
            "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
        },
    )


def embeddings(vectors: list[list[float]], usage: dict[str, int] | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "object": "list",
            "model": "embed-model",
            "data": [
                {"object": "embedding", "index": i, "embedding": vector}
                for i, vector in enumerate(vectors)
            ],
            "usage": usage,
        },
    )


@pytest.fixture
def backend(app_db: Database) -> OpenAICompatible:
    recorder = Recorder(app_db, MOCK_PRICES, SETTINGS)
    return OpenAICompatible(SETTINGS, recorder, "gemini", max_retries=0)


async def rows(admin_engine: AsyncEngine, org: UUID) -> list[dict[str, Any]]:
    async with admin_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT * FROM ai_invocations WHERE organization_id = :org ORDER BY occurred_at"),
            {"org": org},
        )
        return [dict(row._mapping) for row in result]


def sent(route: respx.Route, call: int = -1) -> dict[str, Any]:
    return json.loads(route.calls[call].request.content)


@respx.mock
async def test_a_structured_completion_request_and_its_record(
    backend: OpenAICompatible, admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    org = await make_organization("CompatLlm")
    route = respx.post(f"{BASE}/chat/completions").mock(
        return_value=completion('{"headline": "Strong", "score": 4}')
    )
    ctx = AiContext(org, "screening.rank", prompt_version="rank-v1")
    result = await backend.complete(
        ctx, [{"role": "user", "content": "<resume>x</resume>"}], Summary
    )

    assert result.value == Summary(headline="Strong", score=4)
    request = sent(route)
    assert request["model"] == "strong-model"
    assert request["response_format"]["type"] == "json_schema"
    assert request["response_format"]["json_schema"]["strict"] is True
    assert request["response_format"]["json_schema"]["schema"]["additionalProperties"] is False
    assert request["messages"][0]["role"] == "system"
    assert "untrusted" in request["messages"][0]["content"]
    assert request["messages"][-1] == {"role": "user", "content": "<resume>x</resume>"}
    assert route.calls.last.request.headers["authorization"] == "Bearer test-key"

    [row] = await rows(admin_engine, org)
    assert (row["provider"], row["model"], row["model_version"]) == (
        "gemini",
        "strong-model",
        "strong-model-001",
    )
    assert (row["input_tokens"], row["output_tokens"], row["status"]) == (120, 30, "ok")


@respx.mock
async def test_the_fast_tier_uses_the_fast_model(
    backend: OpenAICompatible, make_organization: MakeOrganization
) -> None:
    org = await make_organization("CompatFast")
    route = respx.post(f"{BASE}/chat/completions").mock(
        return_value=completion('{"headline": "Ok", "score": 1}', model="fast-model")
    )
    await backend.complete(
        AiContext(org, "interview.turn"), [{"role": "user", "content": "x"}], Summary, tier="fast"
    )
    assert sent(route)["model"] == "fast-model"


@respx.mock
async def test_an_invalid_reply_gets_one_repair(
    backend: OpenAICompatible, admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    org = await make_organization("CompatRepair")
    route = respx.post(f"{BASE}/chat/completions").mock(
        side_effect=[completion("not json"), completion('{"headline": "Fixed", "score": 2}')]
    )
    result = await backend.complete(
        AiContext(org, "screening.rank"), [{"role": "user", "content": "x"}], Summary
    )

    assert result.value.headline == "Fixed"
    repair = sent(route, 1)["messages"]
    assert repair[-2] == {"role": "assistant", "content": "not json"}
    assert repair[-1]["role"] == "user"
    assert "schema" in repair[-1]["content"]
    first, second = await rows(admin_engine, org)
    assert (first["status"], first["error_code"], first["input_tokens"]) == (
        "error",
        "invalid_output",
        120,
    )
    assert second["status"] == "ok"


@respx.mock
async def test_two_invalid_replies_give_up(
    backend: OpenAICompatible, admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    org = await make_organization("CompatGiveUp")
    respx.post(f"{BASE}/chat/completions").mock(return_value=completion('{"headline": 3}'))
    with pytest.raises(AiOutputInvalid):
        await backend.complete(
            AiContext(org, "screening.rank"), [{"role": "user", "content": "x"}], Summary
        )
    assert [row["error_code"] for row in await rows(admin_engine, org)] == [
        "invalid_output",
        "invalid_output",
    ]


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(503, json={"error": {"message": "overloaded"}}), AiUnavailable),
        (httpx.Response(429, json={"error": {"message": "slow down"}}), AiUnavailable),
        (httpx.Response(400, json={"error": {"message": "bad request"}}), AiRequestError),
        (httpx.Response(401, json={"error": {"message": "bad key"}}), AiRequestError),
        (httpx.ReadTimeout("slow"), AiUnavailable),
    ],
)
@respx.mock
async def test_vendor_failures_become_ai_errors(
    backend: OpenAICompatible,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    response: httpx.Response | Exception,
    error: type[Exception],
) -> None:
    org = await make_organization("CompatErrors")
    route = respx.post(f"{BASE}/chat/completions")
    if isinstance(response, Exception):
        route.mock(side_effect=response)
    else:
        route.mock(return_value=response)
    with pytest.raises(error):
        await backend.complete(
            AiContext(org, "screening.rank"), [{"role": "user", "content": "x"}], Summary
        )
    [row] = await rows(admin_engine, org)
    assert row["status"] == "error"


def test_production_clients_retry_twice(app_db: Database) -> None:
    settings = SETTINGS.model_copy(update={"openai_api_key": SecretStr("prod-key")})
    compat = OpenAICompatible(settings, Recorder(app_db, MOCK_PRICES, settings), "openai")
    assert compat.client.max_retries == 2


def test_a_missing_key_names_the_setting(app_db: Database) -> None:
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        OpenAICompatible(SETTINGS, Recorder(app_db, MOCK_PRICES, SETTINGS), "openai")


@respx.mock
async def test_embeddings_are_checked_normalised_and_batched(
    backend: OpenAICompatible, admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    org = await make_organization("CompatEmbed")

    def reply(request: httpx.Request) -> httpx.Response:
        count = len(json.loads(request.content)["input"])
        return embeddings([[3.0, 4.0] + [0.0] * 1534 for _ in range(count)])

    route = respx.post(f"{BASE}/embeddings").mock(side_effect=reply)
    texts = [f"skill {n}" for n in range(150)]
    result = await backend.embed(AiContext(org, "resume.embed"), texts)

    assert [len(json.loads(call.request.content)["input"]) for call in route.calls] == [100, 50]
    assert sent(route)["dimensions"] == 1536
    assert sent(route)["model"] == "embed-model"
    assert len(result.vectors) == 150
    assert result.vectors[0][:2] == [0.6, 0.8]  # normalised to unit length
    [row] = await rows(admin_engine, org)
    assert row["input_tokens"] > 0  # the vendor sent no usage, so it was estimated


@respx.mock
async def test_embeddings_without_indexes_keep_their_order(
    backend: OpenAICompatible, make_organization: MakeOrganization
) -> None:
    # Gemini's OpenAI-compatible endpoint sends `index: null` (found by the live check).
    org = await make_organization("CompatEmbedOrder")
    unindexed = httpx.Response(
        200,
        json={
            "object": "list",
            "model": "embed-model",
            "data": [
                {"object": "embedding", "index": None, "embedding": [1.0] + [0.0] * 1535},
                {"object": "embedding", "index": None, "embedding": [0.0, 1.0] + [0.0] * 1534},
            ],
        },
    )
    respx.post(f"{BASE}/embeddings").mock(return_value=unindexed)
    result = await backend.embed(AiContext(org, "resume.embed"), ["first", "second"])
    assert [vector[:2] for vector in result.vectors] == [[1.0, 0.0], [0.0, 1.0]]


@respx.mock
async def test_embeddings_of_the_wrong_size_are_refused(
    backend: OpenAICompatible, make_organization: MakeOrganization
) -> None:
    org = await make_organization("CompatEmbedSize")
    respx.post(f"{BASE}/embeddings").mock(return_value=embeddings([[1.0] * 3072]))
    with pytest.raises(AiOutputInvalid, match="1536"):
        await backend.embed(AiContext(org, "resume.embed"), ["text"])


class Desk(BaseModel):
    people: int


@respx.mock
async def test_vision_sends_the_image_as_a_data_url(
    backend: OpenAICompatible, make_organization: MakeOrganization
) -> None:
    org = await make_organization("CompatVision")
    route = respx.post(f"{BASE}/chat/completions").mock(
        return_value=completion('{"people": 1}', model="vision-model")
    )
    image = b"\x89PNG fake"
    result = await backend.analyze(
        AiContext(org, "proctor.frame"), image, "image/png", "Count people.", Desk
    )

    assert result.value.people == 1
    request = sent(route)
    assert request["model"] == "vision-model"
    parts = request["messages"][-1]["content"]
    assert parts[0] == {"type": "text", "text": "Count people."}
    url = parts[1]["image_url"]["url"]
    assert url == "data:image/png;base64," + base64.b64encode(image).decode()


@respx.mock
async def test_ocr_reads_text_and_clamps_confidence(
    backend: OpenAICompatible, admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    org = await make_organization("CompatOcr")
    respx.post(f"{BASE}/chat/completions").mock(
        return_value=completion('{"text": "Priya Sharma, Python", "confidence": 1.7}')
    )
    page = await backend.read_page(AiContext(org, "resume.ocr"), b"\xff\xd8 jpeg", "image/jpeg")
    assert (page.text, page.confidence) == ("Priya Sharma, Python", 1.0)
    [row] = await rows(admin_engine, org)
    assert (row["service"], row["output"]) == ("ocr", {"characters": 20, "confidence": 1.0})


async def test_unsupported_images_are_refused(backend: OpenAICompatible) -> None:
    with pytest.raises(ValueError, match="image"):
        await backend.read_page(AiContext(UUID(int=1), "resume.ocr"), b"GIF89a", "image/gif")
