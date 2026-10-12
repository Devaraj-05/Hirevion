"""Between LiveKit and the interview engine (SP-09): what the candidate said goes to the
`Conductor`, and what comes back is what the agent says, with the `hv.state` message the desktop
shows (`interview-session.md`). Nothing here touches the room, so it's tested without one."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from redis.asyncio import Redis

from hirevion_core.access.errors import AccessError
from hirevion_core.interview_session.conductor import Conductor, SessionView, Speech, TurnResult
from hirevion_core.interviews.lifecycle import By
from hirevion_core.proctoring import nudges

log = logging.getLogger(__name__)
MAX_BACKOFF_SECONDS = 30.0

STATE_TOPIC = "hv.state"
CONTROL_TOPIC = "hv.control"
CONTROLS = ("done_answering", "repeat", "need_a_moment")
ENDED = ("completed", "evaluating", "evaluated", "abandoned", "cancelled", "expired")
Voice = Literal["listening", "thinking", "speaking", "waiting", "paused", "ended", "error"]


@dataclass(frozen=True, slots=True)
class Spoken:
    """What to say, and the state to show once it's said."""

    text: str
    state: dict[str, Any]
    completed: bool


def state_message(view: SessionView, voice: Voice | None = None) -> dict[str, Any]:
    question = view.question
    return {
        "voice": voice or view.voice,
        "question": {
            "id": question.id,
            "index": question.index,
            "text": question.text,
            "type": question.type,
            "time_limit_seconds": question.time_limit_seconds,
            "workspace": question.workspace,
            "languages": question.languages,
        }
        if question is not None
        else None,
        "remaining_seconds": view.remaining_seconds,
        "notice": view.notice,
    }


class InterviewBridge:
    def __init__(
        self, conductor: Conductor, organization_id: UUID, interview_id: UUID, *, job_id: str
    ) -> None:
        self.conductor = conductor
        self.organization_id = organization_id
        self.interview_id = interview_id
        self._agent = By("agent", job_id)
        self._candidate = By("candidate", "voice")
        self.last_view: SessionView | None = None

    def _spoken(self, result: TurnResult) -> Spoken:
        self.last_view = result.view
        return Spoken(result.say, state_message(result.view), result.completed is not None)

    async def _guard(self, call: Any) -> Spoken | None:
        try:
            return self._spoken(await call)
        except AccessError as error:
            # The interview moved on under us (interrupted, ended, another turn running).
            log.info("Interview %s: %s", self.interview_id, error.code)
            return None

    async def begin(self) -> Spoken | None:
        """The greeting and first question; after a restart, the recovery recap."""
        return await self._guard(
            self.conductor.begin(self.organization_id, self.interview_id, by=self._agent)
        )

    async def recap(self) -> Spoken | None:
        """The candidate came back after an interruption."""
        return await self._guard(
            self.conductor.recap(self.organization_id, self.interview_id, by=self._agent)
        )

    async def heard(
        self,
        text: str,
        *,
        started_at: datetime | None,
        ended_at: datetime | None,
        confidence: float | None,
        acknowledged: bool = False,
    ) -> Spoken | None:
        return await self._guard(
            self.conductor.answer(
                self.organization_id,
                self.interview_id,
                None,
                text,
                mode="voice",
                by=self._candidate,
                speech=Speech(started_at, ended_at, confidence),
                acknowledged=acknowledged,
            )
        )

    async def control(self, action: str) -> Spoken | None:
        if action not in ("repeat", "need_a_moment"):
            return None
        return await self._guard(
            self.conductor.control(
                self.organization_id,
                self.interview_id,
                action,  # type: ignore[arg-type]
                by=self._candidate,
            )
        )

    async def tick(self) -> Spoken | None:
        try:
            result = await self.conductor.tick(
                self.organization_id, self.interview_id, by=self._agent
            )
        except AccessError as error:
            log.info("Interview %s: %s", self.interview_id, error.code)
            return None
        return self._spoken(result) if result is not None else None

    async def voice(self, voice: Voice) -> dict[str, Any] | None:
        """Records the voice state; the `hv.state` message to send, when there's a view."""
        await self.conductor.set_voice(self.interview_id, voice)
        return state_message(self.last_view, voice) if self.last_view is not None else None

    async def ended(self) -> bool:
        """Whether the interview ended somewhere else (the desktop, the scheduler, a recruiter)."""
        view = await self.conductor.session_state(self.organization_id, self.interview_id)
        self.last_view = view
        return view.status in ENDED

    async def candidate_speaking(self, speaking: bool) -> None:
        await self.conductor.candidate_speaking(self.interview_id, speaking)

    async def nudge(self, notice: dict[str, Any]) -> dict[str, Any]:
        """The `hv.state` message that shows a proctoring nudge at once (SP-14): the interview's
        state with the notice."""
        view = await self.conductor.session_state(self.organization_id, self.interview_id)
        self.last_view = view
        return {**state_message(view), "notice": notice}


async def relay_nudges(
    redis: Redis,
    bridge: InterviewBridge,
    publish: Callable[[dict[str, Any]], Awaitable[None]],
    stop: asyncio.Event,
    *,
    block_ms: int = 2000,
) -> None:
    """Publishes each proctoring nudge for this interview as `hv.state` until `stop` is set.
    Nudges from before the agent started are already in the state the desktop reads."""
    last = await nudges.last_id(redis, bridge.interview_id)
    delay = 1.0
    while not stop.is_set():
        try:
            for entry_id, notice in await nudges.read(
                redis, bridge.interview_id, last, block_ms=block_ms
            ):
                last = entry_id
                await publish(await bridge.nudge(notice))
            delay = 1.0
        except Exception:
            # Valkey or the database is down: wait longer each time, up to half a minute.
            log.exception("Interview %s: relaying a nudge failed", bridge.interview_id)
            await asyncio.sleep(delay)
            delay = min(delay * 2, MAX_BACKOFF_SECONDS)
