"""Synthetic candidate that measures voice-interview latency (SP-00c; SP-09's exit criterion).

Start the local stack, the API and the interviewer first:
    uv run hv up --media
    uv run hv seed-identity          # once
    uv run hv api
    uv run python -m hirevion_interview_agent.agent dev
Then:
    uv run hv-voice-bench --turns 20

It seeds a voice interview in the development organisation, signs in and starts it like the
desktop app (so the API dispatches the interviewer), then each turn: waits until the agent is
quiet, speaks a pre-rendered answer (Deepgram TTS), and measures the time from the answer's last
audio frame to the agent's first voiced frame. Answers are cached under tools/voice_bench/.cache/
(gitignored).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import secrets
import time
from collections import deque
from pathlib import Path

import httpx
import numpy as np
from livekit import rtc

from hirevion_interview_agent.agent import load_settings
from hirevion_interview_agent.latency import percentile
from hirevion_interview_simulator.client import DesktopClient
from hirevion_interview_simulator.seed import seed_development_interview

from .audio import Samples, frame_rms, read_wav, split_frames

RATE = 48_000
FRAME_MS = 10
VOICED_RMS = 0.02
QUIET_SECONDS = 1.5
FIRST_AUDIO_TIMEOUT = 30.0
CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache"
DEEPGRAM_SPEAK_URL = "https://api.deepgram.com/v1/speak"
ANSWERS = (
    "I would keep a fixed pool of connections, sized from load tests, and give every "
    "request a short acquire timeout so the service fails fast when the pool is exhausted.",
    "For retries I would use exponential backoff with jitter, and a circuit breaker so a "
    "struggling database doesn't take the whole service down with it.",
    "I would watch pool wait time and active connections, and alert when waits climb above "
    "a few milliseconds for more than a minute.",
    "Idle connections should be validated before reuse and recycled after a maximum "
    "lifetime, so network devices never silently drop them.",
)


def render_answer(text: str, voice: str, key: str, client: httpx.Client) -> Path:
    digest = hashlib.sha256(f"{voice}:{RATE}:{text}".encode()).hexdigest()[:16]
    path = CACHE_DIR / f"{digest}.wav"
    if path.exists():
        return path
    response = client.post(
        DEEPGRAM_SPEAK_URL,
        params={
            "model": voice,
            "encoding": "linear16",
            "sample_rate": RATE,
            "container": "wav",
            "mip_opt_out": "true",
        },
        headers={"Authorization": f"Token {key}"},
        json={"text": text},
    )
    response.raise_for_status()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    return path


class Microphone:
    """Feeds real-time audio: queued speech, otherwise silence."""

    def __init__(self, source: rtc.AudioSource) -> None:
        self._source = source
        self._pending: deque[Samples] = deque()
        self._silence = np.zeros(RATE * FRAME_MS // 1000, dtype=np.int16)
        self.speech_done = asyncio.Event()
        self.speech_ended_at = 0.0

    def say(self, samples: Samples) -> None:
        self.speech_done.clear()
        self._pending.extend(split_frames(samples, RATE, FRAME_MS))

    async def run(self) -> None:
        while True:
            frame = self._pending.popleft() if self._pending else self._silence
            finished_speech = frame is not self._silence and not self._pending
            await self._source.capture_frame(rtc.AudioFrame(frame.tobytes(), RATE, 1, len(frame)))
            if finished_speech:
                self.speech_ended_at = time.perf_counter()
                self.speech_done.set()


class AgentEar:
    """Listens to the agent's audio and timestamps voiced frames."""

    def __init__(self) -> None:
        self.last_voiced = 0.0
        self.heard_anything = asyncio.Event()
        self._watch_from: float | None = None
        self.first_voiced: float | None = None

    def watch_after(self, moment: float) -> None:
        self._watch_from = moment
        self.first_voiced = None

    async def consume(self, track: rtc.Track) -> None:
        async for event in rtc.AudioStream(track, sample_rate=RATE, num_channels=1):
            now = time.perf_counter()
            if frame_rms(np.frombuffer(event.frame.data, dtype=np.int16)) < VOICED_RMS:
                continue
            self.last_voiced = now
            self.heard_anything.set()
            watching = self._watch_from is not None and now > self._watch_from
            if watching and self.first_voiced is None:
                self.first_voiced = now

    async def wait_until_quiet(self, first_audio_timeout: float = FIRST_AUDIO_TIMEOUT) -> None:
        try:
            await asyncio.wait_for(self.heard_anything.wait(), first_audio_timeout)
        except TimeoutError:
            raise TimeoutError(
                "the agent never spoke: is a worker running, and available? "
                "(`agent start` stops taking sessions above 70% CPU; use `agent dev` locally)"
            ) from None
        while time.perf_counter() - self.last_voiced < QUIET_SECONDS:
            await asyncio.sleep(0.05)

    async def wait_for_reply(self, timeout: float) -> float | None:
        deadline = time.perf_counter() + timeout
        while self.first_voiced is None and time.perf_counter() < deadline:
            await asyncio.sleep(0.005)
        return self.first_voiced


async def start_interview(api_url: str) -> tuple[str, str]:
    """A new voice interview, started like the desktop does: the room's URL and the token."""
    seed = await seed_development_interview(text_answers=False, password=secrets.token_urlsafe(18))
    interview = str(seed.interview_id)
    async with httpx.AsyncClient(timeout=30) as http:
        desktop = DesktopClient(http, base_url=api_url, device_name="VOICE-BENCH")
        await desktop.login(seed.email, seed.password)
        briefing = await desktop.briefing(interview)
        check = await desktop.system_check(interview, briefing["mandatory_checks"])
        consent = await desktop.consent(interview, briefing["notice"])
        started = await desktop.start(interview, check["id"], consent["id"])
    return str(started["livekit_url"]), str(started["participant_token"])


async def run(turns: int, candidate_voice: str | None, timeout: float, api_url: str) -> list[float]:
    settings = load_settings()
    deepgram_key = settings.deepgram_api_key.get_secret_value()
    voice = candidate_voice or settings.hv_tts_voice
    with httpx.Client(timeout=60) as client:
        answers = [
            read_wav(render_answer(text, voice, deepgram_key, client))[0] for text in ANSWERS
        ]

    livekit_url, token = await start_interview(api_url)
    ear = AgentEar()
    listeners: set[asyncio.Task[None]] = set()
    room = rtc.Room()

    @room.on("track_subscribed")
    def on_track(track: rtc.Track, *_: object) -> None:
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            task = asyncio.create_task(ear.consume(track))
            listeners.add(task)
            task.add_done_callback(listeners.discard)

    await room.connect(livekit_url, token)
    source = rtc.AudioSource(RATE, 1, queue_size_ms=20)
    options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    track = rtc.LocalAudioTrack.create_audio_track("microphone", source)
    await room.local_participant.publish_track(track, options)
    microphone = Microphone(source)
    mic_task = asyncio.create_task(microphone.run())

    latencies: list[float] = []
    try:
        for turn in range(turns):
            await ear.wait_until_quiet()
            microphone.say(answers[turn % len(answers)])
            await microphone.speech_done.wait()
            ear.watch_after(microphone.speech_ended_at)
            first = await ear.wait_for_reply(timeout)
            if first is None:
                print(f"turn {turn + 1}: no reply within {timeout:.0f} s")
                continue
            latency = first - microphone.speech_ended_at
            latencies.append(latency)
            print(f"turn {turn + 1}: {latency * 1000:.0f} ms")
    finally:
        mic_task.cancel()
        await room.disconnect()
    return latencies


def report(latencies: list[float], metrics_file: Path | None) -> None:
    if latencies:
        print(
            f"measured end of speech -> first AI audio over {len(latencies)} turns: "
            f"p50 {percentile(latencies, 50) * 1000:.0f} ms, "
            f"p95 {percentile(latencies, 95) * 1000:.0f} ms, "
            f"max {max(latencies) * 1000:.0f} ms"
        )
    if metrics_file is None or not metrics_file.exists():
        return
    rows = [json.loads(line) for line in metrics_file.read_text(encoding="utf-8").splitlines()]
    for stage in ("eou", "llm_ttft", "tts_ttfb", "total"):
        values = [float(row[stage]) for row in rows if row.get(stage) is not None]
        if values:
            print(
                f"agent {stage:9}: p50 {percentile(values, 50) * 1000:.0f} ms, "
                f"p95 {percentile(values, 95) * 1000:.0f} ms"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--turns", type=int, default=20)
    parser.add_argument("--candidate-voice", default=None)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="The running API.")
    args = parser.parse_args()
    latencies = asyncio.run(run(args.turns, args.candidate_voice, args.timeout, args.api))
    metrics = load_settings().hv_metrics_file
    report(latencies, Path(metrics) if metrics else None)


if __name__ == "__main__":
    main()
