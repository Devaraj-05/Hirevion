"""The Deepgram backend: speech-to-text (`/v1/listen`) and text-to-speech (`/v1/speak`).

These are the request/response calls for recordings and prompts. The live interview streams
speech through LiveKit's Deepgram plugin instead (SP-09), which records through `Recorder` too.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import httpx

from hirevion_core.ai.recorder import Recorder
from hirevion_core.ai.settings import AiSettings
from hirevion_core.ai.types import (
    AiContext,
    AiOutputInvalid,
    AiRequestError,
    AiUnavailable,
    SpeechAudio,
    Transcript,
    Usage,
    Word,
)

PROVIDER = "deepgram"
DEEPGRAM_URL = "https://api.deepgram.com"
MAX_KEYTERMS = 50
MAX_SPEECH_CHARACTERS = 2000  # Deepgram's limit per /v1/speak request


class Deepgram:
    def __init__(
        self,
        settings: AiSettings,
        recorder: Recorder,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self.recorder = recorder
        key = settings.deepgram_api_key.get_secret_value()
        if client is None and not key:
            raise ValueError(f"the {settings.profile} AI profile needs DEEPGRAM_API_KEY in .env")
        self.client = client or httpx.AsyncClient(
            base_url=DEEPGRAM_URL,
            headers={"Authorization": f"Token {key}"},
            timeout=httpx.Timeout(60.0, connect=10.0),
        )

    async def aclose(self) -> None:
        await self.client.aclose()

    async def _post(self, path: str, **request: Any) -> httpx.Response:
        try:
            response = await self.client.post(path, **request)
        except httpx.TransportError as error:  # includes timeouts
            raise AiUnavailable("Deepgram could not be reached") from error
        if response.status_code == 429 or response.status_code >= 500:
            raise AiUnavailable(f"Deepgram answered {response.status_code}")
        if response.status_code >= 400:
            raise AiRequestError(f"Deepgram refused the request ({response.status_code})")
        return response

    async def transcribe(
        self, ctx: AiContext, audio: bytes, content_type: str, keyterms: Sequence[str] = ()
    ) -> Transcript:
        model = self.settings.stt_model
        params: list[tuple[str, str]] = [
            ("model", model),
            ("smart_format", "true"),
            ("punctuate", "true"),
            ("language", self.settings.stt_language),
        ]
        params += [("keyterm", term) for term in list(keyterms)[:MAX_KEYTERMS]]
        version = model

        async def run() -> Transcript:
            nonlocal version
            response = await self._post(
                "/v1/listen", params=params, content=audio, headers={"Content-Type": content_type}
            )
            try:
                data = response.json()
                metadata = data["metadata"]
                models = metadata.get("models") or []
                if models:
                    version = (
                        metadata.get("model_info", {}).get(models[0], {}).get("version", model)
                    )
                best = data["results"]["channels"][0]["alternatives"][0]
                words = [
                    Word(
                        str(item.get("punctuated_word", item["word"])),
                        float(item["start"]),
                        float(item["end"]),
                        float(item.get("confidence", 0.0)),
                    )
                    for item in best.get("words", [])
                ]
                return Transcript(
                    str(best.get("transcript", "")), words, float(metadata["duration"]), model
                )
            except (KeyError, IndexError, TypeError, ValueError) as error:
                raise AiOutputInvalid("Deepgram's transcription response was malformed") from error

        return await self.recorder.call(
            ctx,
            "stt",
            PROVIDER,
            model,
            run,
            lambda r: Usage(audio_seconds=Decimal(str(r.duration_seconds)), model_version=version),
            lambda r: {"text": r.text},
        )

    async def synthesize(self, ctx: AiContext, text: str) -> SpeechAudio:
        model = self.settings.tts_voice
        if not text.strip():
            raise AiRequestError("there is no text to speak")
        if len(text) > MAX_SPEECH_CHARACTERS:
            raise AiRequestError(
                f"Deepgram speaks at most {MAX_SPEECH_CHARACTERS} characters per call"
            )

        async def run() -> SpeechAudio:
            response = await self._post("/v1/speak", params={"model": model}, json={"text": text})
            content_type = response.headers.get("content-type", "audio/mpeg")
            return SpeechAudio(response.content, content_type, len(text), model)

        return await self.recorder.call(
            ctx,
            "tts",
            PROVIDER,
            model,
            run,
            lambda r: Usage(characters=r.characters, model_version=model),
            lambda r: {"characters": r.characters},
        )
