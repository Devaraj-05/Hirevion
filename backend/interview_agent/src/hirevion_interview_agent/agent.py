"""The AI interviewer (SP-09): a LiveKit Agents worker, dispatched explicitly per interview.

The voice pipeline is Deepgram speech-to-text and text-to-speech through the LiveKit plugins
(PRD §41, §42); the interview engine decides every turn (no "one giant prompt", §34). Each
final transcript goes to the `Conductor`; the agent says what comes back and stops the
pipeline's own reply (`StopResponse`). The desktop sees `hv.state` (voice state, the question,
the time left) and sends `hv.control` (repeat, need a moment, done answering).

One agent per interview holds its Valkey lock; a replacement after a crash waits for the lock,
then resumes from the checkpoint with an apology and the open question again. When the
candidate drops out the agent stays in the room; when they come back it recaps.

Run it (with `uv run hv up --media` already running):
    uv run python -m hirevion_interview_agent.agent download-files   # once
    uv run python -m hirevion_interview_agent.agent dev
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from collections.abc import AsyncIterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    CloseEvent,
    JobContext,
    JobProcess,
    MetricsCollectedEvent,
    ModelSettings,
    StopResponse,
    cli,
    llm,
    room_io,
)
from livekit.agents.metrics import EOUMetrics, LLMMetrics, TTSMetrics
from livekit.agents.voice.events import AgentStateChangedEvent, UserStateChangedEvent
from livekit.plugins import deepgram, silero
from redis.asyncio import Redis

from hirevion_core.ai import build_ai
from hirevion_core.ai.settings import load_ai_settings
from hirevion_core.db.session import create_database
from hirevion_core.engine.phrasing import keyterms, pronounce
from hirevion_core.interview_session.conductor import Conductor
from hirevion_core.interview_session.media import candidate_identity
from hirevion_core.settings import load_core_settings

from .bridge import (
    CONTROL_TOPIC,
    CONTROLS,
    STATE_TOPIC,
    InterviewBridge,
    Spoken,
    relay_nudges,
    state_message,
)
from .latency import LatencyCollector, TurnLatency
from .load import session_load
from .lock import AgentLock
from .settings import AgentSettings

logger = logging.getLogger("hirevion.interview_agent")

TICK_SECONDS = 5.0
ACKNOWLEDGEMENTS = ("Mm-hm.", "Okay.", "Right.", "I see.")
VOICE_STATES = {"listening": "listening", "thinking": "thinking", "speaking": "speaking"}


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


def job_ids(metadata: str) -> tuple[UUID, UUID]:
    """The interview and organisation the dispatch names (set by the API, never the client)."""
    data = json.loads(metadata or "{}")
    return UUID(str(data["interview_id"])), UUID(str(data["organization_id"]))


class Interviewer(Agent):
    """Hands every finished candidate turn to the engine, and never lets a model reply."""

    def __init__(self, bridge: InterviewBridge, speaker: Speaker) -> None:
        super().__init__(
            instructions="You are Hirevion's interviewer. The engine writes every reply."
        )
        self._bridge = bridge
        self._speaker = speaker

    async def on_user_turn_completed(
        self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage
    ) -> None:
        text = (new_message.text_content or "").strip()
        if text:
            await self._speaker.answered(text, new_message.transcript_confidence)
        raise StopResponse()

    def tts_node(self, text: AsyncIterable[str], model_settings: ModelSettings) -> Any:
        """Technical terms are spoken from the lexicon; captions keep the written text."""

        async def spoken() -> AsyncIterable[str]:
            async for chunk in text:
                yield pronounce(chunk)

        return Agent.default.tts_node(self, spoken(), model_settings)


class Speaker:
    """Says the engine's turns in the room and keeps the desktop's `hv.state` current."""

    def __init__(
        self, ctx: JobContext, session: AgentSession[None], bridge: InterviewBridge
    ) -> None:
        self._ctx = ctx
        self._session = session
        self._bridge = bridge
        self._speech_started: datetime | None = None
        self._speech_ended: datetime | None = None
        self._turn = 0
        self._tasks: set[asyncio.Task[None]] = set()
        self.completed = asyncio.Event()

    def background(self, work: Any) -> None:
        """Runs `work` (a coroutine) without blocking the room's event callbacks."""
        task = asyncio.create_task(work)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def publish(self, state: dict[str, Any] | None) -> None:
        if state is None:
            return
        with contextlib.suppress(Exception):
            await self._ctx.room.local_participant.publish_data(
                json.dumps(state), reliable=True, topic=STATE_TOPIC
            )

    async def say(self, spoken: Spoken | None) -> None:
        if spoken is None:
            return
        await self.publish(spoken.state)
        if spoken.text:
            handle = self._session.say(spoken.text, allow_interruptions=not spoken.completed)
            if spoken.completed:
                await handle.wait_for_playout()
        if spoken.completed:
            await self.publish({**spoken.state, "voice": "ended"})
            self.completed.set()

    def user_state(self, event: UserStateChangedEvent) -> None:
        now = datetime.now(UTC)
        if event.new_state == "speaking":
            self._speech_started = now
            self.background(self._bridge.candidate_speaking(True))
        elif event.old_state == "speaking":
            self._speech_ended = now
            self.background(self._bridge.candidate_speaking(False))

    def agent_state(self, event: AgentStateChangedEvent) -> None:
        voice = VOICE_STATES.get(event.new_state)
        if voice is not None:
            self.background(self.voice(voice))

    async def voice(self, voice: str) -> None:
        await self.publish(await self._bridge.voice(voice))  # type: ignore[arg-type]

    async def answered(self, text: str, confidence: float | None) -> None:
        # A short acknowledgement covers the analysis (master plan §6.8's latency path).
        self._turn += 1
        self._session.say(
            ACKNOWLEDGEMENTS[self._turn % len(ACKNOWLEDGEMENTS)], add_to_chat_ctx=False
        )
        spoken = await self._bridge.heard(
            text,
            started_at=self._speech_started,
            ended_at=self._speech_ended or datetime.now(UTC),
            confidence=confidence,
            acknowledged=True,
        )
        self._speech_started = self._speech_ended = None
        await self.say(spoken)

    async def ended_elsewhere(self) -> None:
        view = self._bridge.last_view
        if view is not None:
            await self.publish({**state_message(view), "voice": "ended"})
        self.completed.set()

    async def recap(self) -> None:
        await self.say(await self._bridge.recap())

    async def control(self, action: str) -> None:
        if action == "done_answering":
            self._session.commit_user_turn()
            return
        await self.say(await self._bridge.control(action))


def prewarm(process: JobProcess) -> None:
    process.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext) -> None:
    settings = load_settings()
    core = load_core_settings()
    interview_id, organization_id = job_ids(ctx.job.metadata)
    db = create_database(core, "app")
    redis = Redis.from_url(core.valkey_url())
    ai = build_ai(load_ai_settings(), db)
    lock = AgentLock(redis, interview_id, owner=ctx.job.id)
    conductor = Conductor(db, redis, llm=ai.llm, origin=f"agent:{ctx.job.id}")
    bridge = InterviewBridge(conductor, organization_id, interview_id, job_id=ctx.job.id)

    async def cleanup() -> None:
        await lock.release()
        await ai.aclose()
        await redis.aclose()
        await db.dispose()

    ctx.add_shutdown_callback(cleanup)
    if not await lock.acquire():
        ctx.shutdown(reason="another agent holds this interview")
        return
    state = await conductor.load_state(organization_id, interview_id)
    if state is None or state.ended:
        ctx.shutdown(reason="the interview isn't running")
        return

    await ctx.connect()
    deepgram_key = settings.deepgram_api_key.get_secret_value()
    session: AgentSession[None] = AgentSession(
        vad=ctx.proc.userdata["vad"],
        stt=deepgram.STT(
            model=settings.hv_stt_model,
            language=settings.hv_stt_language,
            api_key=deepgram_key,
            keyterm=keyterms(state),
            mip_opt_out=True,
        ),
        tts=deepgram.TTS(model=settings.hv_tts_voice, api_key=deepgram_key, mip_opt_out=True),
        turn_handling={
            "turn_detection": build_turn_detection(settings),
            "endpointing": {"min_delay": settings.hv_endpointing_min_delay},
            # "adaptive" interruption sends audio to LiveKit Cloud; keep interview audio local.
            "interruption": {"mode": "vad"},
        },
    )
    speaker = Speaker(ctx, session, bridge)
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

    session.on("user_state_changed", speaker.user_state)
    session.on("agent_state_changed", speaker.agent_state)

    @session.on("error")
    def on_error(event: Any) -> None:
        # §33's Error: speech recognition or synthesis failed; the plugins retry and fall back.
        logger.warning("Voice pipeline error in interview %s: %s", interview_id, event)
        speaker.background(speaker.voice("error"))

    @session.on("close")
    def on_close(event: CloseEvent) -> None:
        ctx.shutdown(reason=f"session closed: {event.reason}")

    @ctx.room.on("data_received")
    def on_data(packet: rtc.DataPacket) -> None:
        if packet.topic != CONTROL_TOPIC:
            return
        try:
            action = str(json.loads(packet.data.decode("utf-8")).get("action"))
        except (ValueError, UnicodeDecodeError, AttributeError):
            return
        if action in CONTROLS:
            speaker.background(speaker.control(action))

    returning = {"away": False}

    @ctx.room.on("participant_disconnected")
    def on_left(participant: rtc.RemoteParticipant) -> None:
        if participant.identity == candidate_identity(UUID(state.candidate.id)):
            returning["away"] = True

    @ctx.room.on("participant_connected")
    def on_joined(participant: rtc.RemoteParticipant) -> None:
        if (
            participant.identity == candidate_identity(UUID(state.candidate.id))
            and returning["away"]
        ):
            returning["away"] = False
            speaker.background(speaker.recap())

    await session.start(
        agent=Interviewer(bridge, speaker),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            participant_identity=candidate_identity(UUID(state.candidate.id)),
            # Stay through an interruption: the candidate may come back under the resume policy.
            close_on_disconnect=False,
            # Answers come only from speech here and from the API; no chat input.
            text_input=False,
        ),
    )
    await speaker.say(await bridge.begin())

    async def clock() -> None:
        # Time limits, the end of the interview's time, and endings decided elsewhere (the
        # desktop's "end interview", the scheduler, a recruiter). One failed tick isn't fatal.
        while not speaker.completed.is_set():
            await asyncio.sleep(TICK_SECONDS)
            if lock.lost.is_set():
                speaker.completed.set()
                return
            try:
                await speaker.say(await bridge.tick())
                if not speaker.completed.is_set() and await bridge.ended():
                    await speaker.ended_elsewhere()
            except Exception:
                logger.exception("Interview %s: the clock's tick failed", interview_id)

    ticking = asyncio.create_task(clock())
    # Proctoring nudges (SP-14) reach the desktop as `hv.state` notices, from this agent.
    nudging = asyncio.create_task(relay_nudges(redis, bridge, speaker.publish, speaker.completed))
    await speaker.completed.wait()
    ticking.cancel()
    nudging.cancel()
    ctx.shutdown(reason="interview complete" if not lock.lost.is_set() else "lock lost")


def main() -> None:
    settings = load_settings()
    if settings.hv_turn_detection == "multilingual":
        # The model runs in an inference process that the worker only starts for plugins
        # imported before it starts.
        import livekit.plugins.turn_detector.multilingual  # noqa: F401
    # Explicit dispatch only: the API sends this agent to an interview's room by name.
    os.environ.setdefault("LIVEKIT_AGENT_NAME", settings.hv_agent_name)
    server = AgentServer(
        ws_url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret.get_secret_value(),
        setup_fnc=prewarm,
        load_fnc=session_load(settings.hv_agent_max_sessions),
        load_threshold=1.0,
    )
    server.rtc_session(entrypoint)
    cli.run_app(server)


if __name__ == "__main__":
    main()
