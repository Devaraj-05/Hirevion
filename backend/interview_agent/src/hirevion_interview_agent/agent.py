"""Voice-latency spike agent (SP-00c).

Asks one fixed question, answers each reply in one or two short sentences, and logs
per-turn latency (end of candidate speech -> first AI audio) with its stage breakdown.

Run it (with `uv run hv up` already running):
    uv run python -m hirevion_interview_agent.agent download-files   # once
    uv run python -m hirevion_interview_agent.agent dev
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from livekit.agents import (
    NOT_GIVEN,
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    MetricsCollectedEvent,
    cli,
)
from livekit.agents.metrics import EOUMetrics, LLMMetrics, TTSMetrics
from livekit.plugins import deepgram, openai, silero

from .latency import LatencyCollector, TurnLatency
from .settings import AgentSettings

logger = logging.getLogger("hirevion.interview_agent")

INSTRUCTIONS = (
    "You are Hirevion's technical interviewer in a latency test. "
    "Reply in one or two short spoken sentences, then ask one short follow-up question. "
    "Never use lists, markdown or emoji."
)
OPENING_QUESTION = "Hello! To start, how would you design a connection pool for a busy web service?"


def repo_env_file() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        if (parent / "MASTER_IMPLEMENTATION_PLAN.md").exists():
            env = parent / ".env"
            return env if env.exists() else None
    return None


def load_settings() -> AgentSettings:
    # pydantic-settings fills the fields from the environment and _env_file; mypy only
    # sees the field-based __init__ that pydantic's dataclass transform declares.
    return AgentSettings(_env_file=repo_env_file())  # type: ignore[call-arg]


def build_turn_detection(settings: AgentSettings) -> Any:
    if settings.hv_turn_detection == "multilingual":
        from livekit.plugins.turn_detector.multilingual import MultilingualModel

        return MultilingualModel()
    if settings.hv_turn_detection == "inference":
        from livekit.agents import inference

        return inference.TurnDetector()
    return "vad"


def write_turn(path: Path | None, turn: TurnLatency) -> None:
    row = {
        "speech_id": turn.speech_id,
        "eou": turn.eou,
        "llm_ttft": turn.llm_ttft,
        "tts_ttfb": turn.tts_ttfb,
        "total": turn.total,
    }
    logger.info("turn latency %s", json.dumps(row))
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row) + "\n")


def prewarm(process: JobProcess) -> None:
    process.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext) -> None:
    settings = load_settings()
    deepgram_key = settings.deepgram_api_key.get_secret_value()
    session: AgentSession[None] = AgentSession(
        vad=ctx.proc.userdata["vad"],
        stt=deepgram.STT(
            model=settings.hv_stt_model,
            language=settings.hv_stt_language,
            api_key=deepgram_key,
            mip_opt_out=True,
        ),
        llm=openai.LLM(
            model=settings.hv_llm_model_fast,
            base_url=settings.hv_llm_base_url,
            api_key=settings.gemini_api_key.get_secret_value(),
            reasoning_effort=settings.hv_llm_reasoning_effort or NOT_GIVEN,
        ),
        tts=deepgram.TTS(model=settings.hv_tts_voice, api_key=deepgram_key, mip_opt_out=True),
        turn_handling={
            "turn_detection": build_turn_detection(settings),
            "endpointing": {"min_delay": settings.hv_endpointing_min_delay},
        },
    )
    collector = LatencyCollector()
    written: set[str] = set()
    metrics_file = Path(settings.hv_metrics_file) if settings.hv_metrics_file else None

    @session.on("metrics_collected")
    def on_metrics(event: MetricsCollectedEvent) -> None:
        metric = event.metrics
        if isinstance(metric, EOUMetrics) and metric.speech_id:
            collector.record(metric.speech_id, "eou", metric.end_of_utterance_delay)
        elif isinstance(metric, LLMMetrics) and metric.speech_id:
            collector.record(metric.speech_id, "llm_ttft", metric.ttft)
        elif isinstance(metric, TTSMetrics) and metric.speech_id:
            collector.record(metric.speech_id, "tts_ttfb", metric.ttfb)
        for turn in collector.completed():
            if turn.speech_id not in written:
                written.add(turn.speech_id)
                write_turn(metrics_file, turn)

    await session.start(agent=Agent(instructions=INSTRUCTIONS), room=ctx.room)
    await session.say(OPENING_QUESTION)


def main() -> None:
    settings = load_settings()
    server = AgentServer(
        ws_url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret.get_secret_value(),
        setup_fnc=prewarm,
    )
    server.rtc_session(entrypoint)
    cli.run_app(server)


if __name__ == "__main__":
    main()
