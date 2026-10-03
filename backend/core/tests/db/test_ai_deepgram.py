"""Contract tests for the Deepgram speech backend, with the HTTP API replaced by respx."""

import json
from collections.abc import Awaitable, Callable
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
import respx
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.ai import build_ai
from hirevion_core.ai.deepgram import Deepgram
from hirevion_core.ai.mock import MOCK_PRICES, MockLLM
from hirevion_core.ai.openai_compat import OpenAICompatible
from hirevion_core.ai.recorder import Recorder
from hirevion_core.ai.settings import AiSettings
from hirevion_core.ai.types import AiContext, AiRequestError, AiUnavailable
from hirevion_core.db.session import Database

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]
API = "https://api.deepgram.com"
SETTINGS = AiSettings(
    profile="dev",
    deepgram_api_key=SecretStr("dg-key"),
    stt_model="nova-3",
    tts_voice="aura-2-thalia-en",
)
LISTEN = {
    "metadata": {
        "duration": 2.5,
        "models": ["m1"],
        "model_info": {"m1": {"version": "2025-07-31"}},
    },
    "results": {
        "channels": [
            {
                "alternatives": [
                    {
                        "transcript": "I used FastAPI at Infosys.",
                        "confidence": 0.97,
                        "words": [
                            {
                                "word": "i",
                                "punctuated_word": "I",
                                "start": 0.1,
                                "end": 0.2,
                                "confidence": 0.99,
                            },
                            {"word": "used", "start": 0.2, "end": 0.5, "confidence": 0.98},
                        ],
                    }
                ]
            }
        ]
    },
}


@pytest.fixture
def speech(app_db: Database) -> Deepgram:
    return Deepgram(SETTINGS, Recorder(app_db, MOCK_PRICES, SETTINGS))


async def rows(admin_engine: AsyncEngine, org: UUID) -> list[dict[str, Any]]:
    async with admin_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT * FROM ai_invocations WHERE organization_id = :org ORDER BY occurred_at"),
            {"org": org},
        )
        return [dict(row._mapping) for row in result]


@respx.mock
async def test_transcription_request_and_result(
    speech: Deepgram, admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    org = await make_organization("DgListen")
    route = respx.post(f"{API}/v1/listen").mock(return_value=httpx.Response(200, json=LISTEN))
    keyterms = ["FastAPI", "Infosys"] + [f"term{n}" for n in range(60)]
    transcript = await speech.transcribe(
        AiContext(org, "interview.answer"), b"RIFF audio", "audio/wav", keyterms
    )

    request = route.calls.last.request
    assert request.headers["authorization"] == "Token dg-key"
    assert request.headers["content-type"] == "audio/wav"
    assert request.content == b"RIFF audio"
    params = request.url.params
    assert (params["model"], params["smart_format"], params["punctuate"]) == (
        "nova-3",
        "true",
        "true",
    )
    assert params.get_list("keyterm")[:2] == ["FastAPI", "Infosys"]
    assert len(params.get_list("keyterm")) == 50

    assert transcript.text == "I used FastAPI at Infosys."
    assert [(w.text, w.start, w.end) for w in transcript.words] == [
        ("I", 0.1, 0.2),
        ("used", 0.2, 0.5),
    ]
    assert transcript.duration_seconds == 2.5
    [row] = await rows(admin_engine, org)
    assert (row["service"], row["provider"], row["model_version"]) == (
        "stt",
        "deepgram",
        "2025-07-31",
    )
    assert row["audio_seconds"] == Decimal("2.5")
    assert row["output"] == {"text": "I used FastAPI at Infosys."}


@respx.mock
async def test_speech_request_and_result(
    speech: Deepgram, admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    org = await make_organization("DgSpeak")
    route = respx.post(f"{API}/v1/speak").mock(
        return_value=httpx.Response(200, content=b"ID3 mp3", headers={"content-type": "audio/mpeg"})
    )
    spoken = await speech.synthesize(AiContext(org, "interview.question"), "Tell me about FastAPI.")

    request = route.calls.last.request
    assert request.url.params["model"] == "aura-2-thalia-en"
    assert json.loads(request.content) == {"text": "Tell me about FastAPI."}
    assert (spoken.audio, spoken.content_type, spoken.characters) == (
        b"ID3 mp3",
        "audio/mpeg",
        len("Tell me about FastAPI."),
    )
    [row] = await rows(admin_engine, org)
    assert (row["service"], row["characters"]) == ("tts", len("Tell me about FastAPI."))


async def test_speech_over_the_limit_is_refused_before_any_call(
    speech: Deepgram, make_organization: MakeOrganization
) -> None:
    org = await make_organization("DgLong")
    with pytest.raises(AiRequestError, match="2000"):
        await speech.synthesize(AiContext(org, "interview.question"), "x" * 2001)


@pytest.mark.parametrize(
    ("status", "error"),
    [(429, AiUnavailable), (503, AiUnavailable), (400, AiRequestError), (401, AiRequestError)],
)
@respx.mock
async def test_vendor_failures_become_ai_errors(
    speech: Deepgram, make_organization: MakeOrganization, status: int, error: type[Exception]
) -> None:
    org = await make_organization("DgErrors")
    respx.post(f"{API}/v1/listen").mock(return_value=httpx.Response(status, json={"err_msg": "no"}))
    with pytest.raises(error):
        await speech.transcribe(AiContext(org, "interview.answer"), b"audio", "audio/wav")


@respx.mock
async def test_timeouts_are_unavailable(
    speech: Deepgram, make_organization: MakeOrganization
) -> None:
    org = await make_organization("DgTimeout")
    respx.post(f"{API}/v1/speak").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(AiUnavailable):
        await speech.synthesize(AiContext(org, "interview.question"), "Hello.")


def test_missing_key_names_the_setting(app_db: Database) -> None:
    settings = SETTINGS.model_copy(update={"deepgram_api_key": SecretStr("")})
    with pytest.raises(ValueError, match="DEEPGRAM_API_KEY"):
        Deepgram(settings, Recorder(app_db, MOCK_PRICES, settings))


async def test_build_ai_wires_each_profile(app_db: Database) -> None:
    keys = {
        "gemini_api_key": SecretStr("g"),
        "openai_api_key": SecretStr("o"),
        "deepgram_api_key": SecretStr("d"),
    }
    for profile, provider in (("dev", "gemini"), ("production", "openai")):
        ai = build_ai(AiSettings(profile=profile, **keys), app_db, prices=MOCK_PRICES)  # type: ignore[arg-type]
        assert isinstance(ai.llm, OpenAICompatible)
        assert ai.llm.provider == provider
        assert ai.embeddings is ai.llm and ai.vision is ai.llm and ai.ocr is ai.llm
        assert isinstance(ai.stt, Deepgram) and ai.tts is ai.stt
        await ai.aclose()


async def test_the_mock_profile_reads_scripted_answers_from_a_file(
    app_db: Database, tmp_path: Path
) -> None:
    scripts = tmp_path / "scripts.json"
    scripts.write_text(json.dumps({"jd.extract": {"title": "Scripted"}}), encoding="utf-8")
    ai = build_ai(AiSettings(profile="mock", mock_scripts=scripts), app_db, prices=MOCK_PRICES)
    assert isinstance(ai.llm, MockLLM)
    assert ai.llm.scripted == {"jd.extract": {"title": "Scripted"}}
