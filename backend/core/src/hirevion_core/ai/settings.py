"""AI configuration: the profile, the vendor keys and every model name (never in code)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from hirevion_core.settings import repo_env_file

GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def _env(name: str, env: str) -> AliasChoices:
    return AliasChoices(name, env)


class AiSettings(BaseSettings):
    """`dev` = Gemini + Deepgram, `production` = OpenAI + Deepgram, `mock` = no network
    (ADR-0003). The model names apply to whichever profile is active."""

    model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)

    profile: Literal["dev", "production", "mock"] = Field(
        "dev", validation_alias=_env("profile", "HV_AI_PROFILE")
    )
    gemini_api_key: SecretStr = Field(
        SecretStr(""), validation_alias=_env("gemini_api_key", "GEMINI_API_KEY")
    )
    openai_api_key: SecretStr = Field(
        SecretStr(""), validation_alias=_env("openai_api_key", "OPENAI_API_KEY")
    )
    deepgram_api_key: SecretStr = Field(
        SecretStr(""), validation_alias=_env("deepgram_api_key", "DEEPGRAM_API_KEY")
    )
    gemini_base_url: str = Field(
        GEMINI_OPENAI_BASE_URL, validation_alias=_env("gemini_base_url", "HV_LLM_BASE_URL")
    )
    openai_base_url: str | None = Field(
        None, validation_alias=_env("openai_base_url", "HV_OPENAI_BASE_URL")
    )
    llm_model_fast: str = Field(
        "gemini-3.1-flash-lite", validation_alias=_env("llm_model_fast", "HV_LLM_MODEL_FAST")
    )
    llm_model_strong: str = Field(
        "gemini-3.8-flash", validation_alias=_env("llm_model_strong", "HV_LLM_MODEL_STRONG")
    )
    embedding_model: str = Field(
        "gemini-embedding-2", validation_alias=_env("embedding_model", "HV_EMBEDDING_MODEL")
    )
    embedding_dimensions: int = Field(
        1536, validation_alias=_env("embedding_dimensions", "HV_EMBEDDING_DIMENSIONS")
    )
    vision_model: str = Field(
        "gemini-3.1-flash-lite", validation_alias=_env("vision_model", "HV_VISION_MODEL")
    )
    stt_model: str = Field("nova-3", validation_alias=_env("stt_model", "HV_STT_MODEL"))
    stt_language: str = Field("en", validation_alias=_env("stt_language", "HV_STT_LANGUAGE"))
    tts_voice: str = Field("aura-2-thalia-en", validation_alias=_env("tts_voice", "HV_TTS_VOICE"))
    # The mock profile's fixed answers, as a JSON file of {purpose: answer} (end-to-end tests).
    mock_scripts: Path | None = Field(
        None, validation_alias=_env("mock_scripts", "HV_AI_MOCK_SCRIPTS")
    )
    # The monthly AI spend allowed to an organisation that has no `ai.cost.usd` quota row.
    monthly_budget_usd: Decimal = Field(
        Decimal("50"), validation_alias=_env("monthly_budget_usd", "HV_AI_MONTHLY_BUDGET_USD")
    )


def load_ai_settings() -> AiSettings:
    return AiSettings(_env_file=repo_env_file())  # type: ignore[call-arg]
