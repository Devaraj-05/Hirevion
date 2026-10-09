"""Typed settings for the interview agent, read from the environment or the root .env."""

from __future__ import annotations

from typing import Literal

from pydantic import PositiveInt, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

TurnDetection = Literal["vad", "multilingual", "inference"]
ReasoningEffort = Literal["none", "minimal", "low", "medium", "high"]


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)

    livekit_url: str = "ws://127.0.0.1:7880"
    livekit_api_key: str
    livekit_api_secret: SecretStr
    gemini_api_key: SecretStr
    deepgram_api_key: SecretStr

    # LLM through Gemini's OpenAI-compatible endpoint in development (ADR-0003).
    hv_llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    hv_llm_model_fast: str = "gemini-2.5-flash"
    hv_llm_reasoning_effort: ReasoningEffort | None = None

    hv_stt_model: str = "nova-3"
    hv_stt_language: str = "en"
    hv_tts_voice: str = "aura-2-thalia-en"

    hv_turn_detection: TurnDetection = "vad"
    hv_endpointing_min_delay: float = 0.5
    # Start the LLM on interim transcripts before the turn is confirmed (lower latency, more
    # LLM calls when a turn turns out not to be over).
    hv_preemptive_generation: bool = False
    # The name the API dispatches interviews to (SP-09; explicit dispatch only).
    hv_agent_name: str = "hirevion-interviewer"
    # Sessions one worker takes before LiveKit stops sending it more (see load.py).
    hv_agent_max_sessions: PositiveInt = 10
    hv_metrics_file: str | None = None
